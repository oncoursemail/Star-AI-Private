# STAR — Adaptive Memory, Natural Turn-Taking and Local Inference Research

**Research date:** 2026-11-10  
**Branch:** feat/stream-rehearsal-acceptance-gate-20261110-auto11  
**Scope:** evidence-led roadmap for generalist intelligence, VTuber conversation, gaming and an 8 GB local-GPU deployment  
**Status:** research and evaluation plan; recommendations are not claims of deployed capability or measured gains

## Executive findings

The highest-value next improvements are not another generic "agent" or a larger prompt. They are three measurable control loops:

1. **Adaptive memory policy:** learn which retrieval strategy helps each task, using verified outcomes and a held-out evaluation set.
2. **Natural turn-taking:** optimize the trade-off between false cutoffs and conversational dead air, rather than minimizing endpoint delay in isolation.
3. **Resource-aware local inference:** benchmark prompt processing, token generation, expert-cache behavior, TTS, game rendering and OBS together on the actual machine.

This research also strengthens the cross-lane rehearsal gate: signed evidence must bind to the exact preregistered policy, not merely to a human-readable campaign ID.

## 1. Adaptive memory: choose how to remember and retrieve

### AMA-Bench: memory must preserve objective and causal information

AMA-Bench evaluates memory on long-horizon agent trajectories, not just chat recall. Its authors report that similarity-only retrieval can miss causal and objective information. AMA-Agent combines a causal graph with tool-augmented retrieval and reports 57.22% average accuracy, 11.16 percentage points above the strongest memory baseline in the reported evaluation.

Source: https://arxiv.org/abs/2602.22769

**Application to STAR**

Store compact, provenance-bearing events:

- task or goal;
- observation and source;
- action taken;
- tool/environment response;
- verified outcome;
- confidence and known limitations;
- project/model/environment version.

Represent causal links explicitly (for example, "changed collision group → pickup test began passing") instead of storing only a text summary. A memory entry should be retrievable by project, entity, time, task type, causal predecessor and semantic similarity.

Do not treat an agent's own unverified explanation as an objective outcome. Keep observations, hypotheses and verified facts as distinct record types.

### AEL: evolve the retrieval harness, not just the memory store

The 2026 Findings of EMNLP paper *Agent Evolving Learning (AEL)* studies a two-timescale approach: a fast Thompson-sampling bandit selects among memory/retrieval policies per episode, while slower reflection diagnoses a performance degradation before proposing a new policy. The paper reports improvements on its sequential portfolio and support-ticket routing evaluations; these results do not establish that the same gain will transfer to STAR without testing.

Source: https://aclanthology.org/2026.findings-emnlp.1316/

**Application to STAR**

Start with a small, auditable policy set:

- exact project/entity lookup;
- lexical/BM25 retrieval;
- dense semantic retrieval;
- temporal/episodic retrieval;
- causal-neighbour expansion;
- hybrid retrieval with reranking.

For each task, record only privacy-safe features such as task category, context budget, retrieval latency, source freshness, evidence coverage and verified task outcome. Use a contextual bandit only after a deterministic baseline is established.

Recommended safety/evaluation sequence:

1. Run every policy in shadow mode on the same held-out task set.
2. Score factual support, task success, latency, token cost and contradiction rate separately.
3. Keep a fixed exploration budget; never let the bandit silently expand its own permissions.
4. Require provenance and a minimum evidence threshold before a retrieved memory can be treated as a fact.
5. Use slow reflection to diagnose why a policy failed before adding a new policy arm.
6. Promote a policy only after paired, randomized, held-out evaluation and owner review.
7. Keep rollback metadata for the policy version and its training/evaluation window.

A retrieval policy that is faster but loses the relevant causal dependency is not an improvement.

## 2. VTuber turn-taking: optimize a Pareto frontier

### LiveKit End-of-Turn Benchmark

The open LiveKit EOT benchmark provides aligned human audio and text from 14 languages. It annotates pauses of at least 100 ms and distinguishes genuine end-of-turn pauses from mid-turn hesitation. Its stated evaluation makes the central trade-off explicit: a detector can reduce conversational delay by firing early, but that increases false cutoffs.

Source: https://github.com/livekit/eot-bench

**Application to STAR**

Build a local turn-taking evaluation corpus with consented or public benchmark material, covering:

- short acknowledgements ("yeah", "right", "mm-hm");
- self-corrections and disfluencies;
- long pauses while a person is still thinking;
- overlapping speakers;
- a viewer addressing STAR versus two viewers talking to each other;
- game audio and background noise;
- different speaking rates and microphone qualities.

Report a curve, not one score:

- false-cutoff rate at fixed response-delay budgets;
- median and p95 delay after the true end of turn;
- missed-turn rate;
- addressee accuracy;
- interruption recovery rate;
- performance by language and acoustic condition.

Use hysteresis and conversational context to avoid treating every silence as a turn boundary. Backchannels should generally not seize the floor. Keep a fast endpointing path separate from deeper social/context reasoning, and let the latter revise the decision only while the action is still timely.

Do not optimize for a single human-likeness number. A natural streamer needs accurate timing, appropriate silence, grounded content, interruption recovery and stable identity; these are distinct capabilities.

## 3. Gaming: two clocks, objective outcomes

GameWorld covers 34 browser games and 170 tasks across runner, arcade, platformer, puzzle and simulation genres. It scores success and normalized progress from serialized game state; its real-time track keeps the environment moving during inference.

Source: https://gameworld-bench.github.io/

**Application to STAR**

Use two coordinated loops:

- **Fast control loop:** consume the latest observation, choose a bounded action, enforce an action deadline, and discard stale observations/actions.
- **Slow strategy loop:** plan objectives, map routes, infer mechanics and propose skill updates asynchronously.

The slow planner must never block a time-critical action. Attach timestamps and environment-step IDs to observations. Reject actions if the game has advanced beyond their validity window.

Evaluate across held-out maps/seeds and varied scenarios. Report success, normalized progress, action latency, stale-action rate, recovery rate and scenario diversity. Do not count a repeated easy scenario as transferable mastery.

## 4. Game creation: plan, build, playtest, inspect

Roblox's April 15, 2026 Studio announcement describes structured planning, task manifests, parallel execution and a playtesting agent that reads logs and uses a player character to test behavior. Its July 16, 2026 Build announcement describes a broader AI-assisted creation direction, including playtesting and analytics workflows.

Sources:
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://about.roblox.com/newsroom/2026/07/build-without-limits-on-roblox

**Application to STAR Creator**

Keep the design brief and acceptance criteria pinned across the build:

1. inspect the project and identify existing conventions;
2. produce an editable implementation plan;
3. split independent tasks with explicit file/resource scopes;
4. build in an isolated place/project;
5. run static checks and engine tests;
6. launch a real playtest actor;
7. inspect logs, visual output, physics and interaction outcomes;
8. repair defects and rerun affected plus regression tests;
9. export only verified artifacts through the host-owned promotion boundary.

Track build success, playtest coverage, visual checks, regressions and performance separately. A successful compile is not proof that a game is fun, playable or visually correct.

## 5. Local inference: test the whole machine, not a model in isolation

The upstream llama.cpp MoE-cache documentation describes caching frequently used mixture-of-experts blocks in device memory while keeping other experts in host memory. It also documents a CPU-share option for cache misses; the documentation notes that this can help when host-memory reads are faster than uploading expert weights over the PCIe link. This is workload- and hardware-dependent, not a guaranteed speedup.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

**Application to STAR's RTX 4060 8 GB class host**

Treat expert caching and CPU-share as a controlled experiment only for compatible MoE models. Compare:

- baseline CPU/GPU layer placement;
- model quantization and context length;
- hot-expert cache size;
- CPU share for cache misses;
- pinned versus memory-mapped host weights where supported;
- warm and cold server state;
- concurrent TTS, avatar, game and OBS workloads.

Measure prompt processing, TTFT, inter-token latency, total completion time, tokens/sec, peak VRAM, host RAM, CPU saturation, GPU utilization, game frame-time, OBS dropped frames and first-audible audio. Randomize A/B order, pin the exact llama.cpp commit/model digest and report p50/p95. A higher tokens/sec result is not a win if it causes audio underruns or dropped game frames.

Avoid starting with disaggregated prefill/decode on one 8 GB GPU. First remove avoidable context, stabilize prompt prefixes, reserve VRAM for interactive work, benchmark CPU TTS, and use task-complexity routing with a quality gate.

## 6. Cross-lane evidence must bind to the exact policy

The rehearsal evaluator previously signed a campaign ID, environment and source revision, but the session receipt did not cryptographically bind the complete manifest policy (required lanes, duration, sample minimum and coverage tolerance). Reusing a campaign label with a changed policy could therefore make the intended preregistration less explicit.

The updated evaluator adds:

- a host-generated 256-bit campaign nonce;
- canonical serialization of every manifest policy field;
- a SHA-256 digest of that canonical manifest;
- the manifest digest in the signed session receipt;
- the same manifest digest in every signed lane receipt;
- rejection when session or lane evidence is bound to a different policy.

This prevents accidental policy substitution and makes old signed receipts fail when a new nonce or policy is used. It is not a substitute for secure host key storage, trusted telemetry collection or an external anti-rollback database.

## 7. Prioritized STAR roadmap

| Priority | Work | Acceptance evidence |
|---|---|---|
| P0 | Manifest-bound rehearsal receipts | Policy-substitution and replay regressions |
| P0 | Trusted local telemetry adapter | Independently observed timestamps and counters |
| P0 | Full-repo CI and Windows host acceptance | Clean tests, Pyright, lint, ACL/reparse-point tests |
| P1 | EOT evaluation harness | False-cutoff/latency Pareto curve |
| P1 | Adaptive memory retrieval shadow mode | Paired held-out transfer and latency results |
| P1 | Mixed-workload inference lab | Model quality + voice + game + OBS measurements |
| P1 | Fast/slow game control adapter | Live-clock benchmark with stale-action rejection |
| P2 | Roblox/Godot creator runner | Engine-backed playtests and visual regression evidence |
| P2 | Long-term skill library | Verified reuse on unseen tasks |
| P2 | Private VTuber rehearsal | 30–60 minute session with all lanes measured |

## 8. Non-goals and guardrails

- No claim of human-equivalent intelligence, feelings or consciousness.
- No automatic livestream enablement, public chat actions, purchases, publishing or external side effects.
- No model promotion based only on self-evaluation.
- No retrieval-policy self-modification without held-out evaluation and rollback.
- No raw viewer audio, transcript, screenshot or identity in the cross-lane evidence receipt.
- No assumption that a benchmark result transfers to STAR's hardware or real stream without local measurement.

## 7. VTuber runtime: one event timeline, several real-time loops

STAR should not be a single giant prompt trying to reason over every incoming signal. Use a typed event bus and a shared, bounded world-state snapshot.

### Event contract

Each event should carry:

- monotonic timestamp and sequence number;
- source (microphone, chat, game, OBS, avatar, model, tool);
- event type and schema version;
- confidence and freshness/expiry;
- privacy classification and retention policy;
- correlation ID for the response or action it caused.

Keep separate bounded queues for audio, gameplay, avatar, OBS and background work. Coalesce stale visual observations, drop expired commentary candidates and reject stale game actions. Do not allow a long research task to block the audio or control loop.

### Stream director

A lightweight director should decide which event deserves the next response:

1. safety-critical or user-directed interruption;
2. time-sensitive game event;
3. direct viewer question;
4. relevant group conversation;
5. optional commentary or background thought.

This is a priority policy, not a mandate to speak constantly. Silence is a valid output when STAR has nothing useful or grounded to add.

### Persona and expression

Keep a persistent, versioned persona specification separate from temporary stream state. The persona holds stable voice, humor, boundaries, interests and conversational style. Temporary state holds current game, objective, conversation floor, scene, recent events and the current expressive animation.

Map observable interaction context to explicit expression controls (gaze target, blink, mouth shape, posture, emote and voice prosody). Use actual output audio/phoneme timing for lip sync. Treat expressive states as animation/control labels; do not represent them as proof of subjective feelings or consciousness.

### Viewer interaction and privacy

- Make it clear that STAR is an AI streamer.
- Use ephemeral context by default for ordinary chat.
- Persist viewer preferences only with clear opt-in and an explicit retention/deletion policy.
- Keep private messages, account identifiers and raw audio out of generic long-term memory.
- Apply moderation and privacy filters before text-to-speech.
- Require owner approval for purchases, account changes, publishing, public posts and other consequential external actions.
- Provide visible pause/mute and emergency stop controls.

### Streamer acceptance metrics

Measure response timing, false interruptions, missed addressees, ungrounded statements, speech overlap, audio underruns, lip-sync error, avatar frame drops, game FPS, OBS render/encode lag and dropped frames. Review p50/p95 and failure counts, not just average scores.

STAR's existing cross-modal event-timeline work (PR #1103) is a natural integration point for this shared event contract.

## 8. General knowledge and skill acquisition

A generalist should not rely on one undifferentiated vector database. Use a source-aware knowledge layer:

- **Concept records:** definition, scope, prerequisites, related concepts and confidence.
- **Source records:** URL/document identity, publication/update date, author or institution, license and extraction time.
- **Claim records:** claim text, source span, evidence quality, counterevidence and expiry/recheck date.
- **Skill records:** prerequisites, procedure, tools, tested examples, known failure modes and version.
- **Experience records:** task, environment, action, observed result and verified outcome.

For unfamiliar topics, STAR should identify what it does not know, gather multiple suitable sources, separate facts from hypotheses, attempt a small practical exercise where possible and evaluate on held-out questions/tasks. A source being retrieved often is not proof that it is true.

Recommended knowledge coverage includes science, mathematics, history, engineering, geography, languages, programming, art, music, media literacy, game design, 3D production and practical computer skills. Use a curriculum graph to expose prerequisites and measure retention over time.

For each skill, retain a minimal reproducible example, a positive test, a negative/edge test and a short explanation of when the technique should not be used. This makes knowledge reusable across projects without blindly copying an old solution.

## 9. Capability portfolio and integration boundaries

Build specialist capabilities around shared state and common evidence contracts:

| Specialist | Main job | Independent acceptance |
|---|---|---|
| Researcher | Find, compare and synthesize sources | Citation support, freshness, contradiction checks |
| Programmer | Implement and repair software | Tests, static analysis, review and rollback |
| Game player | Observe and control games | State-verifiable objectives and live-clock metrics |
| Game creator | Plan, build and playtest | Engine execution, visual checks and regression tests |
| Stream co-host | Talk, listen and react | EOT, grounding, addressee and audio metrics |
| Artist/animator | Create visual/audio assets | Format validation, rig/animation checks and human review |
| General tutor | Explain and practice topics | Held-out assessment and calibrated uncertainty |

Specialists should share verified artifacts and provenance, not unrestricted internal state. A coordinator can delegate and compare results, but each tool adapter must enforce its own scope, deadline, resource budget and stop acknowledgement.

## Conclusion

The strongest path to a more capable STAR is an evidence-driven compounding loop: remember causal, verified experience; learn which retrieval strategy works for each task; react quickly without cutting people off; separate fast game control from slow planning; and optimize inference against the complete interactive workload.

The target is not one impressive benchmark score. It is reliable improvement across unseen tasks while preserving voice responsiveness, game performance, privacy and owner control.
