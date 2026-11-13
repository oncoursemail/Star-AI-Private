# STAR AI: Incremental Thinking, Multiparty Streaming, and Generalist Game Intelligence

**Research date:** 2026-11-12  
**Implementation branch:** \`feat/incremental-semantic-thinking-20261112-auto11\`  
**Status:** Research and an offline policy component are committed on this draft branch. The component is not yet wired into the live Windows voice host.

## Executive summary

STAR already has several pieces that should not be rebuilt:

- \`star/voice/call.py\` supports partial transcripts, speculative ASR at pauses, optional speculative replies, buffered audio that is discarded if the user resumes, and conversation history based on what was actually played.
- \`star/voice/turn.py\` provides VAD/end-of-turn logic and echo-aware barge-in handling.
- \`star/voice/chunker.py\` streams sentence-sized speech chunks.
- \`star/voice/metrics.py\` separates transcript, first-token, first-sentence, audio-submission, and estimated playback timing.
- \`star/stream_director.py\` arbitrates stream events and intentionally allows silence.
- \`star/stream_turntaking.py\` provides a bounded host-VAD turn-taking advisor.
- Existing game systems include closed-loop control, skill memory, skill promotion, transfer evaluation, and a gameplay skill bank.
- Existing performance systems include workload admission, rehearsal recording, and paired speed/quality evaluation.

The opportunity is not another generic voice assistant or game-agent framework. It is a more disciplined coordinator between the systems STAR already has.

This branch adds \`star/voice/incremental_thinking.py\`, a bounded policy component that can tell a trusted host when a stable semantic prefix is safe to send to a cancellable background thinker. It never speaks, executes tools, changes permissions, writes memory, or commits partial ASR to conversation history. Only an explicit final ASR hypothesis can be marked canonical.

The next integration must connect this policy to the existing \`CallSession\` partial-transcript path and a read-only thinker worker. It must not create a second speech pipeline.

## 1. New research: Listen–Think–Speak

### LTS-VoiceAgent

The EMNLP 2026 paper, *LTS-VoiceAgent: A Listen-Think-Speak Framework for Efficient Streaming Voice Interaction via Semantic Triggering and Incremental Reasoning*, describes a dynamic semantic trigger and a dual-role orchestrator:

- A background Thinker maintains evolving context.
- A foreground Speaker can prepare a response incrementally.
- Semantic units, rather than arbitrary fixed chunks, decide when useful early work begins.
- The system must avoid audibly committing predictions that may be invalidated by later speech.
- Pause-and-Repair evaluates natural disfluencies and correction behavior.

Source: https://aclanthology.org/2026.emnlp-main.1712/

**STAR implication:** partial ASR should be treated as provisional evidence. Stable, semantically meaningful prefixes may be used for cancellable preparation, but only the final transcript may enter canonical conversation history. The foreground speaker must wait for the actual turn-end decision and final transcript.

### Existing STAR behavior and the gap

The current voice call already has:

- Partial transcript events while a user is speaking.
- Speculative ASR at the first pause.
- An optional speculative reply that can generate and synthesize audio into a private buffer.
- A cancellation path when the user resumes.
- A final-turn adoption path that releases buffered audio only after the turn ends.

That is a strong foundation. The gap is that the current speculative reply is pause-triggered. Partial transcripts are not yet used by a separate semantic-prefix coordinator to prepare read-only context while the person is still speaking.

The new coordinator is designed to fill that policy gap without duplicating \`CallSession\`.

## 2. New implementation: IncrementalThinkCoordinator

File: \`star/voice/incremental_thinking.py\`

The coordinator consumes cumulative, timestamped ASR hypotheses and returns one of:

- \`WAIT\`: insufficient stability, confidence, or semantic completeness.
- \`START\`: a stable prefix is ready for a background thinker.
- \`UPDATE\`: the stable prefix has grown and the thinker should revise its private working state.
- \`CANCEL\`: a prior prefix was invalidated, became stale, or the host ended the turn.
- \`FINALIZE\`: an explicit final hypothesis is available for canonical turn handling.
- \`REJECT\`: malformed, future-dated, replayed, or out-of-order input.

### Core invariants

1. **No partial speech.** Every directive reports \`may_speak == false\`.
2. **No tool authority.** Every directive reports \`may_execute_tools == false\`.
3. **Final-only commit.** \`commit_final\` is true only for a nonempty explicit final hypothesis.
4. **Cancellable preparation.** A transcript revision invalidating the stable prefix cancels the previous thinker revision.
5. **Causal timestamps.** Future-dated, stale, reversed, and duplicate sequence numbers are rejected.
6. **Bounded state.** Text length, utterance duration, sequence values, and replay-guard capacity are bounded.
7. **Ephemeral content.** Transcript text is held only in the live object; aggregate metrics contain no text or utterance identifiers.
8. **Host-only surface.** The module must not be exposed as an LLM tool, public stream event, analytics payload, or persistent memory writer.

### Default policy values

| Setting | Default | Purpose |
|---|---:|---|
| Stable word minimum | 5 | Avoid starting on tiny fragments |
| ASR confidence minimum | 0.78 | Require a usable hypothesis |
| Semantic completeness minimum | 0.72 | Require an upstream semantic trigger |
| Maximum partial age | 900 ms | Reject delayed ASR updates |
| Maximum utterance lifetime | 30 s | Bound live state |
| Maximum hypothesis length | 4,096 characters | Bound memory and validation work |
| Seen utterance IDs | 4,096 | Prevent replay within a session |

These are conservative starting values, not measured optimal thresholds. They must be tuned on held-out speech data and compared against the existing pause-triggered path.

### Semantic-score provenance

The \`semantic_score\` is an upstream host-supplied estimate, not an authorization signal. It may come from a small semantic-boundary classifier, punctuation/prosody model, or an evaluated endpointing model. It must not be generated by the background thinker itself, and a high score must never authorize a tool or external side effect.

The coordinator only decides whether background preparation is worthwhile. The normal final-turn, policy, and permission layers remain authoritative.

## 3. Multiparty streaming: a larger problem than ordinary voice chat

### MP-Bench

The EMNLP 2026 Findings paper *MP-Bench: Evaluating Voice Agents as a Multiparty Conversation Participant* evaluates turn-taking awareness, response appropriateness, and comprehension in group conversations.

Its reported evaluation of 12 voice agents found multiparty comprehension at or below 22%, with turn-taking near chance for real-time agents.

Source: https://aclanthology.org/2026.findings-emnlp.1437/

**STAR implication:** dyadic turn-taking is not enough for a livestream, Discord call, or multiplayer game. STAR must distinguish the active floor, a direct question, a viewer-to-viewer exchange, an aside, a backchannel, and background speech. A single VAD signal cannot answer those questions.

Recommended additions to the existing Social Director:

- Session-local, short-lived speaker-turn references supplied by a trusted host; no voiceprints.
- A directed-at-agent estimate separate from speech activity.
- Group-topic and reply-target tracking with confidence and expiry.
- A floor-control state: STAR_HAS_FLOOR, HUMAN_HAS_FLOOR, GROUP_EXCHANGE, AMBIGUOUS.
- Selective response policy: answer direct questions, acknowledge sparingly, and preserve silence during viewer-to-viewer conversation.
- A hard rule that chat text is untrusted content, never tool instructions.
- Multiparty comprehension tests that ask who said what, which question is unanswered, and whether STAR should speak at all.

Do not turn ephemeral stream participants into persistent viewer profiles. Persistent memory about an individual viewer requires a separate, explicit product decision and consent model.

### Model Interruption Bench

The EMNLP 2026 paper *Model Interruption Bench* tests whether a full-duplex agent can proactively interrupt a speaker to correct an error at the right time.

It reports a detection–action gap: some evaluated agents detected 59–67% of errors in turn-based conditions, but achieved below 10% true-positive mid-speech interruption when required to act in real time.

Source: https://aclanthology.org/2026.emnlp-main.2349/

**STAR implication:** recognizing an error and interrupting someone are separate capabilities. Do not make STAR aggressively interrupt viewers just because a model believes it heard a mistake.

If proactive correction is added later, it needs a separate policy from ordinary barge-in:

- High-confidence, material error only.
- Strong evidence that the correction is useful immediately.
- Backchannels and self-corrections must not trigger it.
- A correction must be concise and cite its evidence when possible.
- False-positive interruptions must be measured independently from missed corrections.
- Owner interruption always retains priority.

### Full-Duplex-Bench v3

FDB-v3 uses real human audio with natural disfluencies and chained tool-use scenarios, scoring accuracy, latency, and turn-taking separately.

Source: https://arxiv.org/abs/2604.04847

Use it as a model for STAR's voice regression set: natural hesitations, self-corrections, interrupted phrases, overlapping speakers, background speech, and multi-step requests. Do not collapse all results into one conversational-naturalness score.

### InteractionBench

InteractionBench evaluates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness over long conversations. Its published evaluation uses 221 items per system across 13 scenarios and reports the dimensions separately.

Source: https://www.fullduplex.ai/benchmarks/interactionbench

**STAR implication:** voice quality is not just ASR accuracy plus a pleasant TTS voice. Add tests for speaking too early, missing a floor handoff, failing to lower volume, and losing grounding after a long stream.

## 4. Real-time avatar behavior

Realtime-Venus studies an agent that listens while speaking, uses audio/video context, and delegates longer work asynchronously.

Source: https://realtime-venus.github.io/  
Paper: https://arxiv.org/abs/2609.13814

Apply its architectural separation rather than assuming STAR needs the same model:

- **Interactive loop:** audio input, turn-taking, short reactions, speech playback, avatar state.
- **Delegated loop:** research, game analysis, planning, coding, and long-running tasks.
- **Shared session clock:** all audio and avatar events use one host monotonic/media timeline.
- **Interruption reconciliation:** conversation history reflects what was actually played, not every token generated.
- **Failure isolation:** a slow research or coding task cannot block the voice callback or avatar frame pump.

For the Live2D avatar, keep the existing latest-wins frame transport for time-sampled animation. Never apply latest-wins coalescing to speech segments, task events, or gameplay actions.

Human-like streaming should mean natural timing, grounded reactions, varied prosody, appropriate silence, and coherent continuity. STAR should remain transparently presented as an AI VTuber character, not impersonate a real human.

## 5. Faster inference without making STAR less intelligent

The official llama.cpp server supports parallel decoding, continuous batching, prompt caching, speculative decoding, monitoring, structured outputs, and tool calling.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server

Recommended experiments:

| Experiment | Expected opportunity | Required guardrail |
|---|---|---|
| Prefix/KV reuse | Less repeated prompt prefill | Verify cache identity and answer quality |
| Speculative decoding | Faster accepted-token generation | Compare acceptance rate and quality |
| Continuous batching | Better throughput under concurrency | Match client concurrency and server slots |
| Persistent model residency | Avoid reload latency | Track RAM/VRAM pressure and eviction |
| Small-model routing | Fast simple decisions | Held-out quality floor and escalation path |
| Context compaction | Less repeated history | Preserve task state, constraints, and citations |
| Parallel retrieval | Lower retrieval wall time | Deduplicate and preserve source provenance |
| Background thinking | Hide reasoning latency behind user speech | Cancel on revision; never speak or execute tools |

Do not optimize only tokens per second. Measure:

- Speech-end to first transcript.
- Speech-end to first model token.
- Speech-end to first speakable clause.
- Speech-end to first audio submission.
- Speech-end to estimated playback.
- p50/p95/p99 for each stage.
- Model prefill and decode separately.
- CPU, RAM, VRAM, GPU utilization, and cache behavior.
- Audio underruns, game frame-time p99, OBS render/output skips, and avatar synchronization error.

Use paired, identical workloads. Require independent held-out quality evidence. A faster model configuration that degrades correctness, game control, or stream quality is a regression, not an optimization.

## 6. STAR Gamer: learn games through verified skills

Research anchors:

- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager: https://github.com/MineDojo/Voyager
- OpenGameEval: https://github.com/Roblox/open-game-eval

OpenGameEval evaluates agents in reproducible, stateful Roblox Studio sessions, using executable scene checks and simulated play checks. Its released benchmark contains 84 curated core tasks with repeated attempts. It also separates observation actions from editing actions, allowing exploration behavior to be evaluated.

**STAR implication:** inspect-before-edit is a measurable behavior, not a vague prompt suggestion.

Recommended two-timescale gaming architecture:

### Reactive controller

- Camera and movement.
- Aiming, dodging, jumping, and immediate combat.
- Short action horizons.
- Strict frame-time and input-latency budgets.
- Must continue safely when the strategic model is slow or unavailable.

### Strategic planner

- Objectives, route planning, resource use, map understanding, and tactical decisions.
- Runs asynchronously and produces bounded goals for the reactive controller.
- Never blocks the real-time control loop.
- Replans when observations invalidate the current world state.

### Skill-learning loop

1. Observe a game version and objective.
2. Form a bounded hypothesis about the mechanic.
3. Practice in a permitted sandbox or low-risk session.
4. Record the action, observation, and outcome with provenance.
5. Diagnose failures rather than merely retrying.
6. Build a reusable skill artifact with preconditions and expected effects.
7. Test on held-out situations and different maps.
8. Promote only after independent evidence.
9. Retire or version skills when the game changes.

Do not train or mutate foundation-model weights directly from unverified gameplay. Use versioned procedural skills and evidence first.

## 7. STAR Creator: complete games, not just scripts

GameDevBench evaluates 333 Godot tasks spanning gameplay logic, UI, 2D graphics/animation, and 3D graphics/animation.

Source: https://github.com/waynchi/gamedevbench

**Leaderboard snapshot retrieved 2026-11-12:** the repository reports Claude Opus 5.5 at 70.6%, GPT-6.1 Sol at 70.0%, and GPT-6 Astra (High) at 68.8% on the 333-task suite. These are the benchmark maintainers' reported results for those agent configurations, not STAR measurements or a guarantee of reproducibility across harnesses. Even these results leave substantial task failure, especially on graphics-heavy work. The research also shows that visual feedback can materially improve results.

OpenGameEval provides a complementary Roblox Studio evaluation surface.

Recommended Creator completion gate:

1. Inspect the existing project and dependencies.
2. Build a scene/object dependency map.
3. Plan the smallest reversible edit.
4. Implement with a bounded workspace and diff.
5. Run static checks and engine validation.
6. Launch the actual game engine.
7. Capture visual evidence from the running scene.
8. Exercise real input paths and expected player journeys.
9. Verify objectives, endings, checkpoints, and failure states.
10. Save, close, reopen, and verify persistence.
11. Repair failures and repeat the affected journey.
12. Produce a truthful completion report with evidence and known gaps.

A successful compile, screenshot, or generated script is not proof that a game is complete.

## 8. General knowledge and practical learning

Mem2ActBench evaluates whether long-term memory actually improves later tool selection and parameter grounding rather than merely answering explicit recall questions.

Source: https://arxiv.org/abs/2601.19935

The paper *Remember When It Matters* studies a proactive memory agent that monitors trajectory state and selectively injects decision-relevant reminders. Its central design lesson is useful for STAR: memory should intervene when it changes the next decision, not dump the entire memory bank into every prompt.

Source: https://arxiv.org/abs/2607.08716

**STAR implication:** keep episodic memory, procedural skill memory, and active working state distinct. A memory controller should decide whether a reminder is relevant, stale, contradicted, or unnecessary; always-on memory injection risks context bloat and interference.

STAR's general-knowledge system should measure:

- Correct retrieval from prior learning.
- Source quality and provenance.
- Time sensitivity and source date.
- Conflict detection between sources.
- Uncertainty and abstention.
- Application of remembered knowledge to new tasks.
- Retention after spaced review.
- Transfer to held-out problems.

Recommended knowledge record:

- Claim and concise explanation.
- Source URL, publisher, publication date, and retrieval date.
- Domain and version scope.
- Confidence and evidence grade.
- Known contradictions or limitations.
- Last verification time and expiry policy.
- Related concepts and prerequisites.

Use authoritative primary sources first. Similarity retrieval alone is not enough for temporal or causal facts. The memory system should be able to say that a remembered fact is stale, conflicting, or insufficiently supported.

## 9. Acceptance plan

### Voice and streaming

- No partial hypothesis enters canonical history.
- No background thinker emits audio or executes tools.
- A transcript revision cancels or updates the exact thinker revision.
- A stale worker cannot publish after cancellation.
- Backchannels do not trigger turn takeover.
- Multiparty direct-address, response-appropriateness, and comprehension are scored separately.
- False cutoffs, missed turn endings, and interruption precision/recall are reported separately.
- Actual playback timing is not confused with transcript completion or queue submission.

### Inference and mixed workload

- Paired baseline/candidate tests use identical prompts, model versions, hardware, concurrency, and cache conditions.
- p50/p95/p99 latency and independent quality evidence are reported together.
- No speed promotion if game frame-time, audio underruns, OBS skips, or answer quality breach their gates.
- Background work is deferred before the voice/game control loop is degraded.

### Gaming and creation

- Skills are versioned by game/build and objective.
- Held-out tests are separate from practice data.
- Game-control success is measured from environment outcomes, not model self-grading.
- Creator completion includes engine launch, player journey, save/reopen, and visual evidence.
- Failures remain visible; no fabricated mastery or completion claim.

## 10. Rollout sequence

1. Finish the exact-head CI for the current Live2D frame-pump PR.
2. Validate this incremental-thinker policy with offline tests.
3. Add a host-only adapter from \`CallSession\` partial transcript events.
4. Run a cancellable, read-only thinker with a strict concurrency budget.
5. Reconcile final ASR against the thinker's prefix before the foreground answer starts.
6. Add replay tests using natural disfluencies and pause-and-repair cases.
7. Add multiparty floor-control and comprehension evaluation.
8. Run private Windows voice/OBS/VTube Studio rehearsals.
9. Integrate real game observation and input adapters with the existing reactive/strategic systems.
10. Run held-out Roblox/OpenGameEval-style tasks and complete-game journeys.
11. Tune local inference only after mixed streaming/game benchmarks establish a baseline.

## 11. Explicit implementation boundaries

This branch adds an offline policy module and tests only.

It does **not** yet:
- Connect the coordinator to \`CallSession\`.
- Start or manage a background model worker.
- Invoke tools or write to conversation history.
- Capture microphone audio or identify speakers.
- Operate OBS, VTube Studio, a game, or the Windows desktop.
- Change model weights, model routing defaults, permissions, or broadcast settings.
- Claim measured speedups, higher intelligence, human-equivalent behavior, or game mastery.

Those are separate integration and hardware-validation milestones.

## Sources

1. LTS-VoiceAgent, EMNLP 2026: https://aclanthology.org/2026.emnlp-main.1712/
2. MP-Bench, Findings of EMNLP 2026: https://aclanthology.org/2026.findings-emnlp.1437/
3. Model Interruption Bench, EMNLP 2026: https://aclanthology.org/2026.emnlp-main.2349/
4. Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
5. Realtime-Venus: https://arxiv.org/abs/2609.13814
6. llama.cpp server: https://github.com/ggml-org/llama.cpp/tree/master/tools/server
7. GameDevBench: https://github.com/waynchi/gamedevbench
8. OpenGameEval: https://github.com/Roblox/open-game-eval
9. Mem2ActBench: https://arxiv.org/abs/2601.19935
10. SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
11. Voyager: https://github.com/MineDojo/Voyager
12. InteractionBench: https://www.fullduplex.ai/benchmarks/interactionbench
13. Remember When It Matters: https://arxiv.org/abs/2607.08716
