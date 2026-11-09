# STAR — Live interaction, generalist capability, and performance validation plan

**Research date:** 2026-11-09  
**Target:** Star's local-first desktop runtime, real-time gaming, Roblox/game creation, and AI-disclosed VTuber streaming.  
**Status:** Research and validation plan; not a claim that the proposed integrations are already deployed.

## Executive direction

Star should be engineered as a coordinated real-time system, not as one large model that is asked to do everything on every frame. Her strongest path is to combine:

1. a low-latency reflex path for immediate game and conversation events;
2. a deeper reasoning path for strategy, research, planning, and creation;
3. evidence-backed memory that preserves provenance and history;
4. a media runtime that synchronizes speech, avatar motion, OBS state, and interruptions;
5. an evaluation and resource governor that only promotes changes after representative tests.

The latest research reinforces a recurring lesson: offline reasoning, benchmark recall, and fast token generation do not by themselves establish real-time competence. Star needs end-to-end evaluation with the game still moving, speech actually playing, and OBS/animation running.

This document separates evidence from hypotheses. Papers' reported scores are results for their own systems and protocols, not measurements of Star.

## 1. New research: interactive livestream understanding

### LiViBench — multimodal livestream tasks

The AAAI 2026 paper *LiViBench: An Omnimodal Benchmark for Interactive Livestream Video Understanding* introduces 24 tasks built around video, audio, speech, and real-time comments. Its annotation process includes human review; the paper also describes a Video-to-Comment Retrieval module and reports results for its LiVi-LLM-7B model on its benchmark.

Why it matters to Star:
- A game frame alone does not explain who is speaking, what a sound means, or which chat message refers to the current event.
- Star should evaluate visual grounding, audio-event grounding, speech understanding, and comment-to-scene matching separately.
- Viewer comments should be treated as untrusted claims until grounded in the current scene or a trusted game event.
- A live comment retrieval system must be time-bounded: a comment about the previous round should not be used as evidence for the current round.

Source: [LiViBench, AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/39859) (published 2026-03-14).

### LiveProBench — when to speak, and when to stay silent

*LiveProBench: Can Streaming Video Models Really Interact Like Humans?* evaluates proactive response timing at one-second stream intervals without an explicit response cue. Its tasks distinguish early, in-window, missed, and duplicate responses.

Why it matters:
- Star needs a silence-quality metric, not just a response-latency metric.
- Every salient event should have a response window and a duplicate-suppression window.
- A correct decision to remain silent is a successful outcome when no useful event occurred.
- Event detection, decision time, first-audio time, and response completion should be measured separately.

Source: [LiveProBench, arXiv:2609.12658](https://arxiv.org/abs/2609.12658) (submitted 2026-09-22).

### Proactive full-duplex systems and role-conditioned turn taking

*Realtime-Venus* describes a full-duplex audio/video interaction architecture with a shared causal timeline for inputs, outputs, and asynchronous delegation. Its reported models are 9B-scale research systems; that makes the architecture an inspiration, not a presumed fit for Star's 8 GB VRAM gaming machine.

*Adaptive turn-taking for real-time multi-party voice agents* (ModeratorLM, Interspeech 2026) studies role-conditioned floor control and chunk-wise streaming speech. Its reported gains are tied to its meeting and synthetic RolePlayConv evaluation. Star should borrow the separation of roles and turn-taking signals, not assume the reported percentages transfer to gaming streams.

Design implications:
- Keep a causal event timeline for audio, ASR partials, game observations, viewer messages, Star speech, and cancellation epochs.
- Represent whether the floor belongs to the owner, a viewer, Star, or another participant.
- Separate nonverbal acknowledgement from verbal turn-taking.
- Make barge-in cancellation a first-class runtime event.
- Prefer a brief cue or silence to a false interruption.

Sources: [Realtime-Venus, arXiv:2609.13814](https://arxiv.org/abs/2609.13814) (2026-09-12); [ModeratorLM, Amazon Science / Interspeech 2026](https://www.amazon.science/publications/adaptive-turn-taking-for-real-time-multi-party-voice-agents).

## 2. Streaming architecture: one causal timeline

Recommended event envelope:

- `session_epoch`: unique for the current private stream/session; invalidates all prior queued media on restart.
- `sequence`: strictly increasing within the epoch.
- `observed_at_monotonic`: trusted host clock, never a model-supplied timestamp.
- `source`: game capture, audio endpoint, ASR, moderated chat, TTS, avatar, or OBS.
- `kind`: allowlisted event type.
- `fresh_until`: deadline after which the event cannot trigger speech or motion.
- `evidence_ref`: opaque reference to a host-owned observation; no transcript or media payload in telemetry.
- `confidence`: bounded host-produced confidence with calibration/version metadata.

The coordinator should make one of four decisions:
1. **speak** — a useful, grounded verbal response fits the event's deadline;
2. **backchannel** — a subtle nonverbal cue is appropriate while another person owns the floor;
3. **defer** — the event is useful but the current workload or conversation state is unsuitable;
4. **silence** — the event is stale, low-value, ambiguous, duplicate, or unsafe to interpret.

Hard invariants:
- A stale event never becomes fresh because a model finishes late.
- A newer event supersedes an older pending commentary item in the same replaceable category.
- Owner speech and owner barge-in preempt optional commentary.
- Critical gameplay preempts ambient commentary and nonessential animation.
- Speech text approval is not audio-playback approval.
- TTS completion is not proof that PCM was physically heard.
- OBS state is not proof that a remote viewer heard the audio.
- A device/route change invalidates pending media tied to the previous route.
- All cancellation paths must carry the same epoch through text, TTS, PCM, avatar, and host output.

## 3. VTuber naturalness: evaluate timing, grounding, and continuity

A convincing AI-disclosed VTuber should not maximize talking time. It should show good conversational judgment.

Recommended behavior:
- Use short, specific reactions for verified game events.
- Let silence persist during concentration, loading, or low-information gameplay.
- Avoid repeating the same acknowledgement or catchphrase.
- Use nonverbal listening cues sparingly and only while the other speaker still owns the floor.
- Ask for clarification when audio or visual evidence is uncertain.
- Distinguish a viewer's claim from something Star independently observed.
- Keep persona continuity across sessions using real recorded experiences and explicitly labeled fictional lore.
- Do not fabricate human memories, offline activities, physical sensations, or private relationships.
- Disclose that Star is an AI when relevant; natural presentation must not become identity deception.

Suggested acceptance metrics:
- event-to-decision latency;
- event-to-first-audio latency;
- event-to-first-visible-avatar-response latency;
- barge-in stop latency and false-stop rate;
- interruption precision/recall;
- duplicate commentary rate;
- missed salient-event rate;
- groundedness and unsupported-claim rate;
- silence precision (remaining silent when no response is warranted);
- voice/viseme synchronization error;
- persona consistency across a 30–60 minute private session.

A response is not successful merely because it is fast. It must still refer to the right event and arrive while that event remains relevant.

## 4. Real-time gaming: reflex loop plus tactical learner

*Gym-Anything-RT* creates 100 visual minigames and compares real-time play with paused/slowed conditions. The paper reports a large gap for evaluated frontier agents between real-time and paused play. This is evidence that deliberative competence and real-time interaction are distinct; it is not a score for Star.

Recommended split:

### Reflex loop
- Consume the newest valid observation, not a backlog of old frames.
- Use compact state features and a small allowlisted action vocabulary.
- Enforce a hard action deadline and reject stale observations.
- Keep actions interruptible and scoped to the owner-approved game/window.
- Use a small controller or policy for high-frequency movement when it is measurably more reliable than repeated large-model calls.
- Record action acknowledgement and result evidence.

### Tactical loop
- Learn objectives, maps, mechanics, routes, cooldowns, resource priorities, and opponent patterns.
- Build a skill hypothesis from multiple episodes.
- Choose targeted practice tasks and adjust difficulty.
- Analyze both failed and successful attempts.
- Test transfer on unseen maps, different frame rates, and altered mechanics.
- Promote a skill only after repeatable held-out success.

### Gaming scorecard
- held-out success/progress by scenario family;
- effective scenario diversity;
- action acknowledgement p50/p95;
- observation age at decision and action time;
- missed deadlines;
- recovery after a failed action;
- transfer to unseen maps and variants;
- performance while OBS, TTS, avatar motion, and inference are active.

Do not train only on one game or one easy map. Do not treat repeated resets of one scenario as broad mastery.

Sources: [Gym-Anything-RT, arXiv:2610.37567](https://arxiv.org/abs/2610.37567) (2026-10-27); [OpenGameEval, arXiv:2610.02563](https://arxiv.org/abs/2610.02563) (2026-10-01).

## 5. Autonomous game creation: inspect first, then test the running game

OpenGameEval runs agents inside reproducible Roblox Studio sessions and evaluates both edited scenes and simulated play. Its paper reports 84 curated tasks across 13 models. It also reports that inspecting objects touched by a reference solution correlates with higher pass rates in its scene-only and script-only tasks. This supports inspection-first workflows, but the correlation should not be presented as universal causation.

Star's creator pipeline should be:

**Inspect → Clarify intent → Plan → Edit → Static checks → Run → Playtest → Visual compare → Repair → Held-out regression → Owner-reviewed release**

Required checks:
- Luau syntax, type analysis, lint, and API-version compatibility;
- scene hierarchy and object properties;
- client/server authority and replication;
- UI layout, scaling, input reachability, and accessibility;
- collision, physics, animation, audio, and asset references;
- multiplayer behavior and exploit resistance;
- performance on low and mid-tier devices;
- actual task completion in simulated play;
- screenshot/scene comparison against a stated visual target.

Use read-only Studio inspection before editing. Keep game publishing, live datastore writes, player moderation, monetization, secrets, and production configuration behind explicit owner approval. MCP/Open Cloud scopes should be minimum-privilege and per-game.

Sources: [Roblox OpenGameEval repository](https://github.com/Roblox/open-game-eval); [Roblox Studio MCP and Open Cloud](https://create.roblox.com/docs/studio/mcp-open-cloud).

## 6. General knowledge and memory that improves actions

Star should not collapse every remembered item into one undifferentiated vector store.

Use typed records:
- **fact** — sourced world or API claim with version/date;
- **observation** — trusted tool or sensor output with freshness and scope;
- **experience** — an action Star actually performed with result evidence;
- **skill** — a reusable procedure that passed repeated and held-out tests;
- **hypothesis** — an unverified explanation;
- **preference** — an explicitly subjective, scoped choice;
- **fictional persona lore** — clearly separated from real events.

Memory pipeline:
1. Extract atomic candidates, never raw transcript dumps by default.
2. Attach source, timestamp, scope, confidence, version, and expiry.
3. Preserve superseded facts as history.
4. Resolve current truth at retrieval time.
5. Retrieve with lexical, vector, temporal, and project/game filters.
6. Rerank only when the task's latency budget allows.
7. Present provenance and uncertainty to the reasoning model.
8. Evaluate whether the memory improves a later action, not just recall.
9. Support abstention when evidence is missing, conflicting, or stale.
10. Prevent cross-project and cross-user memory leakage.

Evaluation should separately test:
- exact fact recall;
- multi-session synthesis;
- temporal updates;
- contradiction handling;
- stale-memory rejection;
- source attribution;
- tool and parameter selection;
- task success using recalled constraints;
- privacy/scope isolation.

Sources: [APEX-MEM, ACL 2026](https://aclanthology.org/2026.acl-long.749/); [LongMemEval](https://github.com/xiaowu0162/LongMemEval); [Mem2ActBench](https://arxiv.org/abs/2601.19935).

## 7. Local inference speed: optimize the full stream, not token/s alone

On an 8 GB VRAM gaming system, the objective is stable end-to-end responsiveness with headroom for the game, OBS, avatar, and audio—not the highest isolated benchmark number.

### Candidate experiments

1. **Prompt/prefix reuse:** keep static persona, tool schemas, and stable project context in a deterministic prefix. Put changing game/chat state after it. Prefix caching can reduce repeated prefill; it does not inherently speed up autoregressive decode.
2. **Speculative decoding:** compare baseline, n-gram speculation, and a small draft model. A resident draft model may consume VRAM that the game and visual workers need.
3. **Context budgeting:** summarize or retrieve only task-relevant history; cap optional visual context; avoid repeatedly sending unchanged frames.
4. **Model routing:** use a small fast model for classification/short reactions, a stronger model for strategic reasoning, and defer deep research while gameplay is time-critical.
5. **CPU speech:** test compact CPU TTS only if it improves first-audio latency and does not starve the game or inference process.
6. **Vision budgets:** reduce worker input pixels only after HUD/scene-quality validation; keep original capture identity and freshness evidence.
7. **Admission control:** pause optional embedding, bulk indexing, deep reasoning, and background generation under GPU, CPU, memory, or audio pressure.
8. **KV/cache isolation:** pin exact runtime versions and test mixed prompt order, session boundaries, and multi-slot behavior before enabling cache reuse optimizations.

### Required benchmark matrix

Run the same synthetic, non-private prompts and the same repeatable game scene under:
- model only;
- game + model;
- game + model + OBS;
- game + model + OBS + TTS + avatar;
- sustained 30–60 minute load.

Record:
- time to first token;
- time to first audio;
- inter-token and inter-chunk latency;
- completion latency;
- p50/p95/p99;
- answer correctness/groundedness on a fixed eval set;
- GPU utilization and VRAM peak;
- CPU utilization and memory peak;
- game FPS and frame-time p50/p95/p99;
- OBS dropped frames;
- audio underruns and route changes;
- game action latency and deadline misses.

Use randomized paired or A/B/A sessions, warm and cold starts, multiple runs, and confidence intervals. A candidate must not be promoted when quality, FPS, OBS stability, or audio reliability regresses. Report missing telemetry as inconclusive, not as zero.

Sources: [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md); [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench); [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/v0.22.1/features/automatic_prefix_caching/); [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).

## 8. Windows audio and OBS host requirements

WASAPI loopback captures the endpoint's rendered mix, which may include unrelated desktop audio. Prefer a dedicated Star output/session and do not persist the loopback stream. Register endpoint notifications; on device invalidation, revoke the old route, cancel queued media, rebuild the endpoint, and require fresh calibration.

OBS WebSocket should:
- retain authentication;
- bind to loopback unless remote access is deliberately configured;
- keep passwords in the OS secret store, not logs or source;
- subscribe only to events needed for the private rehearsal;
- distinguish OBS scene/recording state from proof of physical audio or remote viewer reception.

The Python planner cannot prove that Windows played PCM or that the avatar rig received a parameter update. The trusted native host must provide physical stop/drain evidence and enforce cancellation.

Sources: [WASAPI overview](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi); [WASAPI loopback recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording); [Core Audio device events](https://learn.microsoft.com/en-us/windows/win32/coreaudio/device-events); [obs-websocket security guidance](https://github.com/obsproject/obs-websocket).

## 9. Prioritized implementation roadmap

### P0 — Benchmark correctness and CI
- Keep aggregate request p95 independent from per-category p95.
- Keep token totals all-or-nothing when usage metadata is partial.
- Run offline tests and Pyright baseline checks on every inference change.
- Preserve exact synthetic workload identity and report incomplete evidence as inconclusive.

### P1 — Private Windows streaming rehearsal
- Wire the trusted incremental ASR semantic event source to the existing listener planner.
- Connect WASAPI route identity and device invalidation to the speech route fences.
- Connect VTube Studio/Live2D output to fresh, epoch-bound motion frames.
- Run a private, nonbroadcast 30–60 minute rehearsal.
- Review false interruptions, silence quality, cue naturalness, lip sync, and recovery after device changes.

### P2 — Real-time gameplay learning
- Use the fast reflex loop for immediate actions and a slower tactical learner for skill acquisition.
- Expand balanced, held-out scenario families.
- Require transfer tests before promoting skills.
- Run with OBS/TTS/avatar load active.

### P3 — Generalist memory-to-action
- Add typed temporal memory and source attribution.
- Build LongMemEval-style update/abstention cases and Mem2ActBench-style tool-parameter tests.
- Verify that memories improve task success and never leak between project scopes.

### P4 — Game creation
- Connect inspection-first Studio workflows to static checks, simulated play, visual QA, and held-out regressions.
- Keep publishing and consequential live operations owner-approved.

### P5 — Measured inference optimization
- Benchmark prompt reuse, n-gram speculation, draft models, CPU TTS, and vision pixel budgets separately and in combined stream load.
- Choose the configuration that improves first-audio and gameplay quality of service without regressions, not the one with the best isolated token/s.

## Evidence boundary

This is an engineering research and acceptance plan. The associated code change in this update fixes inference benchmark aggregation and its static typing. It does not install a model, train weights, connect native Windows audio, control a game, operate OBS, or start a broadcast. No neural speedup, gameplay mastery, human-equivalence, or production readiness is claimed.

[executed on device: starai (04f6aa98-0095-4f4d-8546-724e7fb588fa)]