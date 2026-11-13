# STAR proactive audience, audiovisual presence, and game-commentary research

**Research date:** 2026-11-13  
**Target:** `oncoursemail/Star-AI-Project`  
**Branch:** `feat/resource-admission-20261113-run21`  
**Status:** research and integration design; no new model, capture service, or public-stream behavior is enabled.

## Executive decision

STAR should not become a streamer by running a large vision-language model on every frame and asking it to narrate continuously. That approach wastes compute, increases latency, competes with the game renderer, and encourages repetitive commentary.

Build an **event-driven companion runtime** on top of the existing room director, bounded room queue/payload store, task ledger, resource supervisor, and playback-authoritative avatar transport.

The runtime should answer four questions before it speaks:

1. **What happened?** Ground the event in a timestamped observation or trusted game signal.
2. **Does it matter now?** Score urgency, novelty, relevance, and confidence.
3. **Is this a good moment?** Check the conversational floor, game focus, speech backlog, cooldowns, and current resource pressure.
4. **What is the smallest useful response?** Prefer one timely sentence, a brief question, a useful coaching cue, or silence.

This is the path to a natural AI VTuber: attentive and expressive without talking over people, inventing unseen events, or monopolizing the stream.

## 1. Research findings that change STAR's design

### 1.1 Proact-VL and the Live Gaming Benchmark

**Paper:** Proact-VL: A Proactive VideoLLM for Real-Time AI Companions, Proceedings of the 43rd International Conference on Machine Learning, PMLR 306, 2026.

Sources:
- Paper and proceedings: https://proceedings.mlr.press/v306/yan26c.html
- Project page: https://proact-vl.github.io/
- arXiv: https://arxiv.org/abs/2603.03447

The paper identifies three connected challenges for live companions: low-latency processing of continuous video, deciding autonomously when to respond, and controlling both the quality and quantity of generated content. Its Live Gaming Benchmark separates solo commentary, co-commentary, and user-guidance scenarios.

**STAR transfer:**
- Separate event detection from language generation.
- Keep a rolling, bounded visual context rather than replaying the entire stream.
- Make the decision to speak before spending tokens on a response.
- Evaluate solo commentary, co-commentary, and coaching separately.
- Score timing and content quality independently.
- Treat an event-triggered response as a hypothesis until its visual/game evidence is checked.

Do not copy a research model into the runtime merely because it is described as real-time. First reproduce the relevant task on STAR's target hardware and compare end-to-end quality and latency.

### 1.2 MP-Bench: multiparty conversation is a hard capability

**Paper:** MP-Bench: Evaluating Voice Agents as a Multiparty Conversation Participant, arXiv:2609.13076; accepted to EMNLP 2026 Findings.

Sources:
- Paper: https://arxiv.org/abs/2609.13076
- Evaluation repository: https://github.com/atosystem/MP-Bench

The benchmark contains 927 tasks for a four-person spoken conversation: three simulated humans and the agent. It includes 543 discussion-understanding tasks, 128 discussion behavior tasks, and 256 turn-based game tasks. The behavior tasks explicitly balance speaking and staying silent. The paper reports that the evaluated real-time voice agents reached at most 22% multiparty comprehension and remained near chance on multiparty turn-taking.

**STAR transfer:**
- Track who said what, who was addressed, and which prior event a reply belongs to.
- Score whether silence was correct, not just whether an answer was generated.
- Separate comprehension, turn-taking, response appropriateness, and latency.
- Test structured turn-based interactions as well as open discussion.
- Do not treat dyadic voice-call success as evidence of multiparty competence.

**Data restriction:** the MP-Bench repository explicitly says its tasks and audio are for evaluation only and must not be used to train a model. STAR should use the benchmark only under its stated protocol and license; build separate consented practice data for any training or adaptation.

### 1.3 VideoFDB: natural presence requires audiovisual behavior

**Paper:** VideoFDB: Evaluating Full-Duplex Vision-Speech Capabilities in Conversational Agents, arXiv:2605.30256v2 (2026-07-28).

Sources:
- Paper: https://arxiv.org/abs/2605.30256
- NVIDIA project page: https://research.nvidia.com/

VideoFDB contributes 237 real two-person video-call clips spanning 11 nonverbal conversational dynamics. It separates perception behavior from generation behavior. The paper reports that tested systems often use vision for explicit visual questions but fail to use it for continuous audiovisual grounding; it also identifies limitations in cascaded speech-to-avatar pipelines for full-duplex nonverbal cues.

**STAR transfer:**
- Evaluate what STAR notices separately from what her avatar expresses.
- Model listening and speaking as distinct avatar states.
- Let gaze, attention, and listening expressions respond to the current speaker and conversational context.
- Keep lip-sync tied to actual played audio, not generated text.
- Permit listening expressions while no speech is playing, but never fabricate mouth movement or an audible response.
- Test nonverbal perception and nonverbal generation as separate capabilities.

VideoFDB's evaluation data is not a default training corpus. Check the paper and dataset license before any use; the benchmark listing describes gated, non-commercial evaluation terms.

## 2. One event spine for audio, chat, game, and avatar state

The existing room architecture already has a strong foundation:
- #1171: content-free room turn director.
- #1172: room decisions connected to CallSession playback/cancellation.
- #1173: bounded metadata queue.
- #1174: short-lived payload store.
- #1175: queued room-message execution.
- #1176: opt-in desktop room host.
- #1177: durable task and communication ledger.
- #1178: linked human-resolution STOP semantics.

Extend these through one causal event envelope. Do not create another voice pipeline or a second scheduler.

Recommended envelope fields:
- session and stream epoch;
- opaque event ID and optional causal parent/event being resolved;
- source: audio, chat, game, or host telemetry;
- host-monotonic observation and expiry times;
- opaque session-scoped speaker/addressee IDs;
- event class and confidence;
- urgency and novelty;
- evidence reference or immutable evidence hash;
- scene/version fingerprint;
- consent and source-policy decision;
- delivery/response generation ID when applicable.

Keep raw audio, transcripts, viewer identities, and video out of the metadata queue. Content should remain in the existing bounded, short-lived payload boundary. Persist only the minimum owner-approved summaries and evidence references needed for long-term learning.

## 3. Proactive commentary director

The current room director handles classified cues, including high-urgency game events. It does not itself provide a complete continuous visual-observation or proactive-commentary system. Add that capability only when a trusted observation adapter exists.

### 3.1 Observation path

1. Read cheap, trusted signals first: game events, scene changes, input state, audio VAD, playback cursor, and host health.
2. Sample frames adaptively when the scene changes or a relevant event is suspected.
3. Reuse cached scene/object representations while the scene remains stable.
4. Send short event windows—not the entire stream—to a more capable vision model when needed.
5. Attach timestamps and scene fingerprints to every observation.
6. Reject stale observations when the scene epoch changes before the response is admitted.

Avoid maximum-rate full-resolution vision inference. It can starve the game, OBS, TTS, and the local language model.

### 3.2 Decide before generating

A deterministic policy should combine:
- confidence that the event actually occurred;
- urgency and time sensitivity;
- novelty relative to recent commentary;
- relevance to the current game objective or conversation;
- whether STAR is being addressed;
- whether another person is already speaking;
- whether the event has already been handled;
- speech backlog and cooldown;
- current CPU, RAM, VRAM, GPU, audio, and OBS headroom.

Possible outcomes:
- **IGNORE:** duplicate, stale, irrelevant, or unsupported event.
- **WAIT:** evidence or classification is insufficient.
- **QUEUE:** useful but not time-critical while STAR is busy.
- **RESPOND:** concise commentary or answer is appropriate now.
- **INTERRUPT:** a high-confidence, time-critical event justifies preemption under the configured policy.
- **STOP:** a linked human has already resolved the exact request.

Do not optimize for maximum talk time, chat-message count, or engagement at any cost. The policy must be allowed to choose silence.

### 3.3 Commentary styles

Keep response style separate from event classification:
- **Companion:** brief, warm reaction to a meaningful event.
- **Co-commentator:** concise play-by-play without repeating obvious screen content.
- **Coach:** actionable suggestion when the player wants help.
- **Learner:** asks a short clarifying question when a mechanic is unfamiliar.
- **Creator:** explains a development decision while building or testing a game.

Use the same character contract and voice identity across modes. Do not make the personality prompt responsible for safety, tool permissions, or factual grounding.

## 4. Nonverbal VTuber controller

Treat the avatar as a second output channel with its own state and timing.

Recommended states:
- idle/listening;
- attentive to a named speaker;
- thinking;
- speaking;
- interrupted;
- amused/laughing;
- surprised;
- focused on gameplay;
- celebrating;
- confused/uncertain;
- recovering after a tool or stream error.

Rules:
- Lip-sync follows the speaker's actual playback cursor.
- A stopped or invalidated audio generation must stop its associated mouth animation.
- A newer expression/frame supersedes stale queued frames (latest-wins transport).
- Eye focus follows the current addressee or relevant screen region only when supported by perception.
- Listening motion may continue during speech input, but speaking animation must not be inferred from text generation.
- Reduced-motion and owner disable controls remain respected.
- Facial expression intensity should be bounded by evidence confidence; do not turn every classifier label into exaggerated emotion.

Related work to integrate, not duplicate: #1159 Live2D latest-wins transport and the existing epoch-bound PCM/playback protections.

## 5. Gaming intelligence: separate reflex, tactics, and learning

A general game agent should not ask a large language model to choose every frame-level input.

**Reflex layer**
- bounded movement, camera, timing, and emergency responses;
- low-latency deterministic controller where a safe game-specific interface exists;
- strict input limits and immediate stop/cancel.

**Tactical layer**
- objectives, routes, resources, inventory, combat plans, teammate coordination;
- consumes compact state snapshots and recent event history;
- requests a new plan only when the state meaningfully changes.

**Learning layer**
- practice in a private sandbox or benchmark;
- compare strategies on multiple seeds and held-out levels;
- turn successful behavior into a versioned skill with preconditions, actions, postconditions, evidence, and known failure cases;
- reject a skill that only memorizes one map or one seed;
- measure transfer to unseen tasks before promotion.

For Roblox, keep Studio inspection, editing, Play testing, and publishing as separate permission boundaries. A successful code generation is not a successful game: require Play-session evidence, regression checks, visual inspection, and rollback.

## 6. General knowledge and grounded explanations

STAR should distinguish:
- retrieved information;
- a model's prior knowledge;
- an inference;
- a claim verified against an authoritative source;
- a skill demonstrated by successful execution.

For current game mechanics, API behavior, or software versions, retrieve current official documentation and record the source/version. For gameplay explanations, ground claims in the observed scene or game state. If evidence is missing, say what is unknown rather than filling the gap with plausible narration.

Long-term memory should store concise event summaries and verified lessons with provenance, timestamps, confidence, and correction history. Viewer-specific memory requires explicit policy and consent; session speaker IDs should be ephemeral by default.

## 7. Speed and resource plan for an 8 GB GPU desktop

Use the existing authoritative resource path (#1140/#1142) and the paired evaluator (#1166). Do not add another admission controller.

Priority order:
1. Remove duplicate model calls and duplicate TTS preparations.
2. Keep prompts stable and cacheable; retrieve only the few relevant skills/memories.
3. Separate fast classification/turn decisions from slow planning.
4. Sample/crop/cache visual input adaptively rather than running a large VLM continuously.
5. Benchmark context and KV-cache sizes before increasing context length.
6. Compare quantization and speculative decoding only with matched model, prompt, context, and concurrency.
7. Keep audio callbacks and frame delivery off blocking model/tool work.
8. Protect CPU/GPU/VRAM headroom for the game, OBS, and speech.
9. Run expensive research, model training, and video generation off-stream or on a secondary machine.
10. Route background jobs through the same lease-based supervisor and cancel stale work.

A candidate is faster only if it improves the end-to-end path without reducing task accuracy, grounding, or gameplay/stream stability.

## 8. Evaluation matrix

Use the benchmarks for the behavior they actually measure; do not combine their scores into one misleading “human-likeness” number.

| Layer | Evaluation source | STAR-specific acceptance |
|---|---|---|
| Multiparty comprehension and turn-taking | MP-Bench | Correct speaker/event tracking, appropriate response, correct silence |
| Audiovisual nonverbal perception and generation | VideoFDB | Separate perception and avatar-generation scores; playback-aligned timing |
| Proactive game commentary and guidance | Proact-VL Live Gaming Benchmark | Solo commentary, co-commentary, and user guidance evaluated separately |
| Room event handling | Existing STAR room tests | Exact event linkage, dedupe, expiry, cancellation generation, no double reply |
| Voice delivery | Existing rehearsal and stream evaluation | First audible latency, interruption recovery, no stale PCM |
| Mixed-load performance | #1166 paired evaluator + host telemetry | p50/p95/p99 latency, game frame-time, OBS skips, audio underruns, CPU/RAM/VRAM |
| Game skill transfer | GameWorld / Roblox OpenGameEval and private holdouts | Success on unseen maps/seeds/mechanics, not only memorized tasks |
| Game creation | GameDevBench / Roblox Studio Play tests | Build validity, Play-session outcomes, visual and regression checks |

For every candidate, compare against a pinned baseline using the same model hash, quantization, context, prompt, tools, hardware, and workload. Preserve holdouts. Report sample counts and confidence intervals. If the test does not have enough evidence, mark it inconclusive rather than passing it.

## 9. Phased implementation plan

**Phase A — Replayable evaluation**
- Add MP-Bench-compatible evaluation adapter without importing evaluation audio into training.
- Add VideoFDB-style perception and avatar-generation scorecards using separately licensed/consented test clips.
- Add Proact-VL-style solo/co-commentary/guidance scenarios to the existing private rehearsal harness.
- Store only aggregate metrics and opaque case IDs.

**Phase B — Trusted observation adapters**
- Connect one game observation source at a time.
- Validate monotonic timestamps, scene epochs, source allowlists, and stale-event rejection.
- Keep vision sampling adaptive and resource-aware.
- Keep commentary disabled by default until the private replay suite passes.

**Phase C — Private local rehearsal**
- Run a nonbroadcast session with game + OBS preview + avatar + speech + local model.
- Test multi-speaker interruption, human resolution, silence, laughter, scene changes, game danger, and tool latency.
- Measure first audible response and p99 game/OBS/audio metrics.

**Phase D — Owner-controlled stream rollout**
- Explicit owner enablement for each platform/source.
- Visible AI disclosure.
- Viewer consent and moderation controls.
- Emergency stop, mute, and disconnect.
- No autonomous public posting, spending, account changes, or game publishing without the applicable owner approval.

## 10. Existing repository integration map

- #1140/#1142: single resource supervisor and stream-pressure governor.
- #1159: latest-wins Live2D frame transport.
- #1165/#1166: spoken-task and paired realtime evaluation.
- #1167: streamed inference first-content/token timing.
- #1171–#1176: multiparty room director, queue, payload, execution, and opt-in host.
- #1177: durable task/communication ledger.
- #1178: linked human-resolution stop semantics.

Keep these contracts authoritative. Before implementing a new adapter, inspect its parent PR and the exact target-branch API. Do not introduce parallel schedulers, voice pipelines, telemetry authorities, or benchmark frameworks.

## 11. Immediate engineering backlog

1. Fix and rerun the exact-head CI failures in the current #1178 branch before adding more runtime surface.
2. Add a benchmark adapter for MP-Bench scoring, respecting its evaluation-only restriction.
3. Add a VideoFDB-inspired private audiovisual rehearsal rubric; do not ingest gated benchmark data without license.
4. Add solo commentary, co-commentary, and user-guidance replay scenarios to the existing paired evaluator.
5. Define the trusted game-observation event contract and scene epoch.
6. Connect one read-only game adapter before any game-control adapter.
7. Add event novelty/cooldown only after the event schema and replay fixtures are stable.
8. Run a private mixed-load rehearsal on the owner's actual Windows/RTX 4060 machine.
9. Keep every new capability OFF by default until its acceptance evidence is recorded.

## Sources

- Yan et al., Proact-VL, PMLR 306 (2026): https://proceedings.mlr.press/v306/yan26c.html
- Proact-VL project page: https://proact-vl.github.io/
- Shih et al., MP-Bench, arXiv:2609.13076 (2026): https://arxiv.org/abs/2609.13076
- MP-Bench evaluation repository and data-use restriction: https://github.com/atosystem/MP-Bench
- Mazumdar et al., VideoFDB, arXiv:2605.30256v2 (2026): https://arxiv.org/abs/2605.30256
- NVIDIA VideoFDB project page: https://research.nvidia.com/
- OpenTelemetry GenAI metrics (Development status; pin the convention version): https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
