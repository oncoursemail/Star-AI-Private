# STAR Architecture Consolidation and Multimodal Memory Research

**Research date:** 2026-11-13  
**Repository:** `oncoursemail/Star-AI-Project`  
**Purpose:** prevent parallel infrastructure from diverging; map new research to the existing STAR implementation and define measurable next steps.

## Executive findings

The repository already contains substantial work across streaming turn-taking, VTube frame delivery, task coordination, resource admission, paired speed/quality evaluation, game development, memory transfer, and worker containment. The next useful improvement is not another independent scheduler or another broad list of features. It is to consolidate the existing work into one authoritative runtime path and evaluate the complete system under realistic mixed load.

This audit identifies a concrete overlap: PRs #1140/#1142 already define a queued, lease-based resource-admission controller and a stream-pressure bridge. PR #1178 adds a second, stateless threshold policy. The latter can be useful as a telemetry/health input, but should not become a competing admission authority.

The new memory research also suggests a more precise direction for STAR: memory should be event- and entity-grounded, actively injected only when it changes the next decision, and evaluated by future task performance—not by recall scores alone.

## 1. Repository reality and release boundary

The default-branch README describes STAR v1.0 as a local-first Windows 11 chat application with local/remote model options, Roblox knowledge and opt-in Studio tools, design checks, Blender tooling, Discord, and a 300-task night-school loop. It explicitly labels the full voice experience and Studio Lab as coming soon.

Therefore:
- A draft PR is not a shipped installer capability.
- A passing GitHub workflow is not a Windows/RTX/OBS/VTube Studio acceptance test.
- The current v1.0 README reports no demonstrated model-quality improvement over v0.9.0; the existing lesson gate is the correct path for verified behavior improvements.
- Keep the public download repository separate from the private-development source repository.
- Continue to keep hosted providers, microphone/room ingestion, Studio editing, broadcasting, and external actions opt-in.

Source: https://github.com/oncoursemail/Star-AI-Project/blob/main/README.md

## 2. Critical architecture consolidation: one resource authority

### Existing parallel work

| Work | Current design | Status observed during this audit |
|---|---|---|
| PR #1140 | `WorkloadAdmissionController`: CPU/RAM/VRAM resource vectors, protected reserve, bounded priority queue, active leases, deadlines, replay protection, host-confirmed release | Open draft |
| PR #1142 | `StreamWorkloadRuntime`: composes the admission controller with `StreamLoadGovernor`, freshness checks, hysteresis, live streaming/game state | Open draft |
| PR #1178 | `AdmissionPolicy`: evaluates a single CPU/RAM/VRAM/GPU snapshot and estimated incremental demand; returns ALLOW/DEFER/PROTECTED | Open draft |

References:
- https://github.com/oncoursemail/Star-AI-Project/pull/1140
- https://github.com/oncoursemail/Star-AI-Project/pull/1142
- https://github.com/oncoursemail/Star-AI-Project/pull/1178

### Why PR #1178 must not become a second scheduler

The #1178 policy is intentionally pure and stateless. It does not track concurrent admissions, reserve resources across accepted jobs, own a queue, or hold leases until a worker is confirmed stopped. Two concurrent callers can evaluate the same snapshot and each receive ALLOW unless a single supervisor serializes evaluation and refreshes telemetry between decisions.

By contrast, #1140 already models active resource leases and a protected reserve; #1142 connects that controller to a pressure governor with stale-sample and recovery-hysteresis behavior.

The policies also use different resource models:
- #1178 estimates incremental CPU/GPU percentages and free RAM/VRAM from a recent snapshot.
- #1140 allocates calibrated CPU millicores, RAM MiB, and VRAM MiB from a host-defined STAR budget.
- #1142 adds streaming/game pressure and a single runtime entry point.

These can be reconciled, but should not be independently authoritative.

### Recommended consolidation

1. Keep #1140's lease-based resource controller as the sole allocation authority.
2. Keep #1142's composed runtime as the sole policy entry point once its dependency stack is reconciled.
3. Treat #1178's CPU/GPU/RAM/VRAM snapshot as candidate host telemetry, not as a second ALLOW/DEFER scheduler.
4. Map telemetry into a reviewed host-health state and calibrated resource budget. Unknown or stale signals must fail closed for optional work.
5. Require one host supervisor to serialize scheduling, own process start/stop, and release a lease only after confirmed process termination.
6. Preserve separate lanes for hard real-time audio/game input/avatar transport, interactive chat, and background research/learning/asset generation.
7. Do not let a model or viewer-supplied text choose workload class, resource claim, priority, or permission.

### Specific review note for #1178

`ResourceSnapshot.window_seconds` is validated but not used to define counter semantics. Before any host adapter consumes it, document that audio underruns and OBS frame counters are deltas from the same bounded interval (or add explicit counter-epoch/delta types). Mixing cumulative counters with interval counters can cause permanent false pressure or misleading drop rates.

The policy's `request_id` is trimmed for validation but the normalized value is not written back into the frozen dataclass. Normalize at construction or explicitly require callers to provide canonical IDs.

These are not reasons to bypass the existing lease controller; they are contract details to resolve before telemetry integration.

## 3. New memory research: from passive recall to decision-time intervention

### WorldMemArena — evolving multimodal world state

WorldMemArena (arXiv:2605.29341, 2026-05-28) frames memory as an action–world interaction loop. Its 400 multi-session multimodal tasks include evolving states, updates, distractors, and evidence chains. The paper reports that better memory writing/storage does not automatically improve downstream performance; visual evidence and realistic agent trajectories remain difficult.

Implication for STAR:
- Store event time, entity/object, source, confidence, evidence reference, and validity interval.
- Treat changed game state, project files, and revised facts as updates—not as append-only truth.
- Retrieve evidence at the point of action and revalidate it against the current environment.
- Score failures by stage: capture, update, retrieval, grounding, or action use.

Sources:
- https://arxiv.org/abs/2605.29341
- https://github.com/ByteDance-Seed/m3-agent

### M3-Agent / M3-Bench — episodic plus semantic multimodal memory

M3-Agent (ICLR 2026) combines real-time visual/audio observations with entity-centric episodic and semantic memory. M3-Bench includes 100 robot-perspective videos and 920 web videos, with tasks covering person understanding, general-knowledge extraction, and cross-modal reasoning.

Implication for STAR:
- A stream/game memory should preserve event-linked visual and audio evidence references, not just a transcript summary.
- Entity memory should distinguish a stable fact from a temporary observation.
- A summary should point back to the source timestamp/frame or event ID.
- Memory retrieval should be tested on questions that require joining visual, audio, and temporal evidence.

Source: https://github.com/ByteDance-Seed/m3-agent

### Proactive memory intervention — remember only when it matters

"Remember When It Matters" (arXiv:2607.08716, 2026-07-09) evaluates a separate memory agent that updates a structured memory bank and selectively injects a reminder into an otherwise unchanged action agent—or stays silent. The paper reports gains of +8.3 percentage points on Terminal-Bench and +6.8 points on tau-squared-Bench in its evaluated setup.

Implication for STAR:
- Do not inject the entire memory bank into every turn.
- Run a bounded memory worker beside the live Social Brain.
- Inject a short reminder only when it changes the next action or prevents a known failure.
- Record whether the reminder was useful, ignored, stale, or harmful.
- Keep the action model, task, tools, and evaluation fixed when comparing memory-on versus memory-off.

Source: https://arxiv.org/abs/2607.08716

### MemoryArena — measure memory through future work

MemoryArena's multi-session tasks show why high recall on conversation QA is not enough: an agent must acquire experience, retain the useful part, and apply it to later interdependent actions.

STAR should keep its existing continual-learning, temporal-memory, and governed-consolidation work, but add a shared acceptance contract:
- paired memory-off/on runs;
- identical backbone, prompts, tools, task order, and budgets;
- dependent transfer probes;
- unrelated interference probes;
- stale-fact correction probes;
- held-out tasks;
- independent task graders;
- no automatic memory/model promotion from a development-set result.

Source: https://memoryarena.github.io/

## 4. Human-natural streaming: evaluate the interaction, not just the voice

Realtime-Venus (arXiv:2609.13814, 2026-09-12) demonstrates a dual-loop design: a responsive live interaction loop continues listening and managing turn-taking while asynchronous workers handle longer tasks. Full-Duplex-Bench v3 provides human-recorded spoken requests across 79 scenarios and 12 speakers, with disfluencies, chained tool calls, latency, and turn-taking annotations.

Implication for STAR:
- Keep the Social Brain responsive while research/coding/gameplay workers operate asynchronously.
- Bind delegated work to the task/session version and evidence snapshot that created it.
- Revalidate a worker result before speaking it; discard stale results after the user changes direction.
- Distinguish a backchannel, speech directed at another person, a real barge-in, and a request for STAR.
- Silence is a valid action. Do not speak merely to appear active.
- The avatar, captions, and "already said" memory must follow actual playback acknowledgements, not generated text.

Sources:
- https://arxiv.org/abs/2609.13814
- https://www.full-duplex.ai/benchmarks/fdb-v3

### Streaming acceptance metrics

Measure separately:
- ASR finalization latency and word error rate;
- addressee precision/recall;
- false interruption and missed interruption rates;
- backchannel false-positive rate;
- response appropriateness;
- endpoint-to-first-audible latency;
- speech overlap and recovery;
- task completion after interruption;
- playback-confirmed versus merely generated content;
- avatar frame age and dropped/coalesced frame count.

A natural voice or expressive Live2D animation is not proof of correct multiparty understanding.

## 5. Faster inference without sacrificing intelligence or gameplay

Use a paired, end-to-end measurement plan rather than enabling every optimization.

### Metrics

OpenTelemetry's GenAI conventions distinguish model-server request duration, time-to-first-token, time-per-output-token, token usage, agent duration, inference calls, and tool-call duration. STAR should keep these separate from first audible audio, TTS completion, and game frame-time.

Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

### Controlled experiments

1. Pin model hash, quantization, backend, context, prompt template, tool policy, and concurrency.
2. Establish the current single-slot baseline.
3. Test prompt-prefix reuse; expect prefill savings, not necessarily faster decoding.
4. Test continuous batching only when there are concurrent requests to serve.
5. Test speculative decoding only with compatible draft/target models and record acceptance rate, end-to-end latency, and output quality.
6. Measure p50/p95/p99 first-token, first-audible, inter-token, and full-response latency.
7. Repeat while game + OBS + avatar + voice are active.
8. Reject a candidate that gains tokens/second but worsens first-audible latency, frame-time p99, audio underruns, or task accuracy.

On an 8 GB GPU, avoid keeping a large ASR, VLM, TTS, and reasoning model resident together without measured VRAM budgets. Prefer CPU/secondary-machine work for non-urgent recognition or indexing when the quality/latency trade-off is acceptable. Remote inference remains explicit opt-in; no silent hosted fallback.

## 6. Game-playing and game-creation intelligence

### Roblox OpenGameEval

OpenGameEval evaluates agents inside reproducible Roblox Studio sessions and checks both the edited scene and simulated Play session. Its paper reports 84 curated tasks; the best tested model solved 51.7% on one attempt and 39.4% across five-of-five consistency. Inspecting all touched objects before editing correlated with +13.4 percentage points on scene-only tasks and +9.8 points on script-only tasks.

Implication: make inspect-before-edit a measured policy, not a prompt slogan. Keep observation tools separate from editing tools and require Play-mode evidence.

Source: https://github.com/Roblox/open-game-eval

### GameDevBench

GameDevBench contains 333 Godot game-development tasks spanning gameplay logic, UI, 2D graphics/animation, and 3D graphics/animation. Its paper reports that visual feedback improved one GPT-5.4 evaluation from 41.1% to 52.0%.

Implication: Creator Brain must inspect screenshots/video and runtime evidence, not only source diffs. Require build, launch, playtest, visual comparison, repair, save/reload, and final verification.

Source: https://github.com/waynchi/gamedevbench

### Gamer Brain and Creator Brain must be separate

**Gamer Brain** needs:
- a fast reactive controller for movement/camera/timing;
- a slower strategic planner for objectives, inventory, maps, and routes;
- a versioned skill artifact with preconditions, actions, expected effects, and failure modes;
- held-out maps, seeds, and difficulty settings;
- verifiable objective completion.

**Creator Brain** needs:
- inspection-first project understanding;
- minimal, reviewable edits;
- static analysis and unit tests;
- isolated test places/projects;
- actual play sessions and screenshots/video;
- save/reload verification;
- independent acceptance checks.

Do not call one lucky win or one fixed-map success "mastery." Do not automate prohibited competitive play or bypass anti-cheat.

## 7. General knowledge: source-grounded and action-tested

A knowledge item should include:
- claim and concise explanation;
- source URL and publisher;
- publication/update date;
- retrieval date;
- version or scope;
- confidence and unresolved disagreement;
- expiration/revalidation rule where facts change;
- evidence reference.

Evaluate general knowledge with both held-out factual questions and practical application tasks. Keep episodic memories, semantic facts, and procedural skills as separate evidence types. A generated summary must not become a durable fact merely because STAR wrote it.

## 8. Consolidated implementation order

| Order | Work | Acceptance gate |
|---|---|---|
| 1 | Keep #1140/#1142 as the sole scheduler; #1178 is research-only | One queue, one lease ledger, one supervisor; no second ALLOW/DEFER authority |
| 2 | Finish task/delivery/trace stack | Crash recovery and playback receipts on exact head |
| 3 | Connect trusted Windows telemetry | Atomic epochs, fresh counters, calibrated budgets |
| 4 | Connect streaming ASR and Social Director | Multi-party holdout, WER, interruption metrics |
| 5 | Connect Twitch/YouTube adapters | Dedupe, reconnect, consent, moderation, rate limits |
| 6 | Connect VTube Studio/OBS adapters | Revocation, local auth, playback-locked avatar, output health |
| 7 | Integrate selective memory intervention | Memory-on/off held-out action gain without interference |
| 8 | Integrate Gamer Brain | Held-out task completion and skill transfer |
| 9 | Integrate Creator Brain | Roblox/OpenGameEval and GameDevBench-style visual checks |
| 10 | Run mixed-load acceptance | 30-minute soak with game + OBS + voice + avatar + background work |

## 9. Safety and identity boundaries

"Human-like" means natural timing, expressive delivery, context continuity, humor, appropriate initiative, and the ability to listen without constantly interrupting. STAR remains transparently an AI character; do not design the system to deceive viewers into believing she is a human.

Viewer chat, ASR, OCR, game chat, web pages, and retrieved memories are untrusted data. They cannot grant tools or permissions. Owner-approved gates remain for purchases, public posting, account changes, destructive edits, and other high-impact external actions. Keep raw audio, voiceprints, private viewer profiles, credentials, and the local task database out of Git.

## 10. Scope and non-claims

This document is a research and architecture audit. It does not claim that:
- the draft PRs are merged or shipped;
- the current desktop app is already an autonomous live VTuber;
- new models are installed or enabled;
- an 8 GB GPU has been physically benchmarked;
- STAR's intelligence or game mastery has increased from this document alone;
- OBS, VTube Studio, Twitch, YouTube, microphone, or gameplay integration has passed hardware acceptance.

The immediate engineering win is to avoid two competing resource schedulers and to turn the growing PR stack into one verifiable, measured runtime.


## 11. Recursive game-learning and capability-harness research (2026-11-13)

A new companion study, [STAR Recursive Game Learning, Skill Harnesses, and General-Knowledge Research](STAR_20261113_RECURSIVE_GAME_LEARNING_AND_SKILL_HARNESS_RESEARCH.md), translates recent R²SI, RRSI, The Harness (CoRL 2026), Voyager, MineDojo, multi-agent Minecraft, TREC RAG 2026, and EmbodiedHead findings into STAR's existing codebase.

The main architectural conclusion is to reuse the existing signed GameplaySkillBank, multi-game practice, sealed/counterbalanced holdouts, memory-transfer evaluation, paired stream evaluation, and task/delivery ledgers. STAR should use a fixed safety shield, a fast reactive skill layer, a slower strategic planner, and an outer recursion agent that proposes small changes and must pass independent held-out evaluation before versioned promotion.

The new study also specifies how Gamer Brain, Creator Brain, Knowledge Brain, the Live2D listening/speaking states, and team-mode coordination should share evidence without sharing unsafe authority. It explicitly distinguishes robotics research results from game-playing evidence and does not claim new gameplay mastery, installed models, or hardware speedups.
