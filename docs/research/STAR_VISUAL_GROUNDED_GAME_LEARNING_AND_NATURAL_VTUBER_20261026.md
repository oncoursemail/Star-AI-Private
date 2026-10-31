# STAR: evidence-grounded gameplay, general intelligence, and human-natural VTubing
**Research and implementation note — October 26, 2026.** Experimental; no claim of model-weight improvement or production broadcasting.

## Executive engineering finding

The most consequential missing interface in STAR's recent game-learning chain was a real source of time-bound visual evidence. The existing `GameActionGate`, `StudioPlaytestHost`, `StudioOutcomeBridge`, `GameplaySkillBank`, `GameTransferEval`, and `GameLearningLadder` were already present, but examples still constructed `GameFrame` with synthetic image hashes. This branch adds the **read-only observation component** `star/studio_visual_evidence.py`, using the official Studio MCP tool names, a **real decoded screenshot**, an owner-selected in-memory image assessor, private-focus attestations, and a scope-separated SHA-256 digest. It never sends game input, trains on private footage, or treats model confidence as independent success evidence.

The essential loop remains:
`Studio MCP Play -> capture real screen -> host-scoped GameFrame -> bounded policy -> private game input -> separately verify outcome -> signed PRACTICE trial -> held-out skill transfer eval`.

This branch implements the **capture-to-frame portion only**. Do not market it as autonomous gameplay until hardware-host input and actual evaluations are connected.

## Source evidence checked 2026-10-26

1. Roblox's current Studio MCP documentation lists `list_roblox_studios`, `get_studio_state`, `screen_capture`, `user_keyboard_input`, and playtest controls; Studio MCP is a **local stdio transport** and sessions are selected by `studio_id`: https://create.roblox.com/docs/studio/mcp . Built-in MCP/playtest announcement: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 .
2. Roblox's 2026 Playtest Agent beta can verify gameplay scenarios via a Studio subagent; it is an optional separate evaluation approach, not proof of STAR's own performance: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 .
3. Roblox OpenGameEval requires executable checks and stateful scene observation for game-building agents. Its public research reinforces separating tool availability from actual task success: https://arxiv.org/abs/2610.02563 and https://academy.dair.ai/papers/opengameeval-benchmarking-agentic-programming-and-exploration-in-a-stateful-game-2610.02563 .
4. Kyutai Pocket TTS is a **100M-parameter CPU-oriented audio-streaming candidate**; first-chunk latency and realtime factors on its published demo machines are **not** predictions for STAR's PCs: https://kyutai-labs.github.io/pocket-tts/ .
5. Kyutai Moshi investigates speech-to-speech **full-duplex** turn-taking and overlap. Its published ~200 ms lower-latency result applies to specific hardware, not 8 GB gaming cards: https://github.com/kyutai-labs/moshi and https://arxiv.org/abs/2410.00037 .
6. llama.cpp documents speculative decoding including draft-model, cache, and EAGLE-3 variants. It does **not** guarantee a speedup or compatibility for STAR's model: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md .
7. VTube Studio's official API allows custom Live2D parameter injection via an authenticated plugin connection; STAR's existing stage/motion/Live2D layers must be tested with actual synchronized **heard** audio: https://github.com/DenchiSoft/VTubeStudio .
8. Twitch EventSub WebSockets have keepalive, duplicate-delivery, reconnect, lost-session resubscription, and authorization rules; STAR's new Twitch host is still owner-opt-in and not a substitute for moderation: https://dev.twitch.tv/docs/eventsub/handling-websocket-events .

## Code in this branch

### `StudioVisualObserver`

- **Access policy**: no implicit permission. `arm(owner_approved=True)` is required. A trusted host callback must separately attest that this precise `studio_id` is an authorized *private local playtest* in focus. Never let model text or viewer chat implement the callback.
- **Real session check**: `list_roblox_studios` must contain the exact requested Studio; `get_studio_state` must unambiguously be `Playing`. We do not launch Studio, switch modes, or edit the DataModel.
- **Actual screenshot**: `screen_capture` returns exactly one PNG/JPEG MCP image block; the observer strictly base64-decodes and bounds it (8 MiB) before calling an injected async visual assessor. Absent/ambiguous/mislabeled/oversized frames are rejected, not "filled in" from the LLM.
- **Identity and provenance**: per-frame scope includes Studio ID, game, version, and episode, and the cryptographic frame digest binds *those fields plus actual screenshot bytes*. The raw screenshot never becomes a file, conversation memory, analytics record, or GitHub artifact.
- **Monotonic freshness**: a screenshot gets the host's monotonic capture-start time; late analysis does not magically refresh its timestamp. `GameActionGate` must independently refuse a stale frame at the time of action. The `actionable_when_captured` hint is **not** an input permit.
- **Inference efficiency**: the latest image SHA-256 is retained. Identical frames reuse a recent classification (up to 500 ms); they receive **zero actionable confidence** so a motionless or frozen game frame cannot repeatedly authorize the same input. No raw pixel cache.
- **Revocation**: the owner/host may disarm during a slow assessment; a generation counter prevents the completed assessment from being accepted afterward. No attempted key-up is needed because the observer itself never presses keys.
- **Bounded output**: no screenshot data in `VisualEvidence`, only digest, byte count, low-trust one-line scene summary, change flag, scope, and GameFrame. This reduces video-privacy and logging risk.

`VisualAssessment` is *not ground truth*. A visual model might misidentify a platform, health bar, game UI, or victory screen. Require independent engine-evaluated signed trials before learning an actual success rate. Separate (a) screenshot identity, (b) model inference, (c) game outcome, and (d) withheld generalization evaluation.

### Trusted-host integration contract

Run STAR's official Studio `connect()` on the **Windows PC with Roblox Studio**, discover the tool catalog, pin a specific Studio instance, choose a **trusted** local assessor, and pass the established MCP client to `StudioVisualObserver`. The optional existing host launcher can bridge a Windows Studio from another machine if explicitly configured; do not expose Studio MCP on the internet. The trusted host must own focus/authorization, private-place verification, frame clock, error telemetry, and subsequent action dispatch.

Do **not** treat a mere `screen_capture` success as game success. Use the existing `StudioPlaytestHost` input safety and `StudioOutcomeBridge` signed trial flow. Do not issue actions to public multiplayer games under this private-playtest policy.

Acceptance test: intentionally capture one private training level; confirm that image SHA changes when the scene changes, that exact duplicates give 0 actionable confidence, that switching to Edit or revoking host authorization refuses capture, that secrets/images are not written to disk, that an attempted stale action is rejected, and that a separate evaluator signs outcome only after observing a real checkpoint change.

**Known integration gap:** The exact real Studio `screen_capture` response content and latency can vary by Studio version; these tests use a protocol-shaped fake image block, not a live Studio. Discover the live schema and adapt only after a device pilot, maintaining strict bounds. STAR's Studio processes were not running during this research pass.

## Intelligence roadmap: prioritize measured outcomes, not more prompt text

**P0: close the live perception-action-evaluation loop.** Connect a currently opened private Roblox Studio on Brain 2. Measure per-stage p50/p95 camera capture, image assessor, action gate, input release, and engine outcome. Retain source digests and objective receipts; do not record a learning improvement from a chatbot assertion.

**P1: run learning ladders with hard holdouts.** Partition game seeds/maps/mechanics into TRAIN/PRACTICE versus PRIVATE HOLDOUT before any training. Run equal-budget baselines and agents with the same CPU/GPU budget; compare successful unique scenarios, steps-to-solution, failures, resets, and transfer across games. Track variance and manual qualitative reviews. No overfitting on a visible test suite.

**P2: richer eyes and game-building QA.** Use `screen_capture` plus game-tree, instance-property, and console evidence to generate a *structural scene report*. Check wall continuity, unintended intersections, spawn reachability, texture seams, anchors/physics, UI safe areas, and animation clipping. Provide localized diffs and repair proposals, not giant unverified rebuilds. Add human aesthetic review before release. Store screenshots only in a reviewed, private, expiring local test cache if explicitly permitted.

**P3: general-knowledge competence.** Route questions to fresh documentation or existing reviewed local knowledge, with source date/provenance and explicit "unknown" answers. Cluster contradictory claims and expire volatile facts. Use expert-grade, source-grounded retrieval and separate private research from facts approved for stream. The existing `KnowledgeStore` and `public_knowledge_packet` are a foundation; AI-generated text must never automatically become authenticated knowledge. Evaluate on unseen, properly scored factual questions and calibration—not answer length.

**P4: AI-native internal self-improvement.** Star Core Forge should stage experiment branches, immutable baseline manifests, a clean-room test environment, cost/quality telemetry, failure triage, guarded promotion, semantic change explanations, backups, and rollback. GitHub remains an optional reviewed publishing endpoint, *not required for Star's autonomous local operation*. Do not silently self-update a live streaming runtime or overwrite curated eval answers.

## Faster reasoning on an 8 GB gaming GPU

1. **Baseline first.** Record live in-game FPS frametime p95/p99, VRAM headroom, CPU utilization, RAM usage, model cold start, prompt/cache-hit rate, first token, token throughput, first audible speech, and last audible/animation drift. Run each variant across identical seeds and sessions.
2. **Do less work.** Reuse verified scene and retrieval summaries; skip identical video frames; don't run expensive vision on unimportant periods; cap source snippets and prioritize active goals. These save resources before choosing a larger neural model.
3. **Preserve graphics priority.** Apply existing `stream_qos.py` and realtime benchmark gates: if game frametimes deteriorate or audio is backlogged, pause background training/rendering/research, shrink image input, and prefer CPU-only speech when quality permits. Never oversubscribe VRAM or steal GPU while games hitch.
4. **Benchmark quantization/caching/speculative decode.** Draftless n-gram cache may have a better VRAM tradeoff than a separate speculative draft model on a small card. Validate actual token acceptance, KV-memory usage, game FPS, quality and latency. Discard losing configurations. Never claim that nominal FLOPS equals higher intelligence.
5. **Route by difficulty.** Fast small models can handle low-risk factual or short chat turns; harder game-reasoning tasks may need more deliberation, tool observations and verification. Use best-of-N only off the real-time critical path and only when verifier cost is justified.
6. **Separate offline learning from streaming.** Night practice, compilation, asset builds, research indexing, scene-quality checks and multi-agent challenges should be GPU/CPU budgeted outside active streams. Resume via checkpoint, not by restarting whole jobs.

These are testable hypotheses, **not measured gains** from the new observer.

## A human-natural, clearly AI VTuber

STAR should be recognizable and warm without pretending she has a human body or fabricated offline experiences. Her durable persona can have preferences and a playful history, yet distinguish story/lore from what genuinely occurred in a game or chat.

- **Low-friction conversation:** lightweight VAD and turn prediction, brief context before answering, bounded deliberate pauses, interruptible speech with immediate neutral motion, and short acknowledgements that don't monopolize gameplay. Avoid "replying to every message" and repeated catchphrases.
- **Expressive voice:** benchmark Pocket TTS CPU streaming against existing voice engines; include breath/no-breath transitions, phoneme timing, intelligibility, prosody variation, laughs and emotional believability. Use only consented voice assets; do not clone a real person's voice without permission. Moshi is an architectural reference, not a drop-in 8 GB GPU dependency.
- **Physical animation:** coordinate recorded-audio playback with lip sync, expressive eye movements, blinks, shoulders, physics-based twin-tail hair, ears/tail in cat/puppy modes, head/gaze adjustments and speaking/listening posture. VTube Studio parameter maps need an actual Live2D rig and device pilot. Reactions should reflect observed events, not imaginary victories.
- **Focus beats constant talking:** during a difficult fight, talk less; afterward, describe what actually happened. Read chat selectively with moderated Twitch EventSub, private IDs pseudonymized, replay/spam bounded, and no viewer authority over device actions.
- **Persistent but governed memory:** recall game achievements and opted-in public viewer preferences with expiration and edits. Do not treat private chat logs as broadcast material. If Star tells a fictional story, mark it as fiction, not autobiographical fact.

## Evaluation ledger (must be populated by a real device pilot)

| Area | Measured protocol | Release criterion (proposed, not achieved) |
| --- | --- | --- |
| Eyes | `screen_capture` + Studio state + hash, 50 private scenes | 0 false private-session grants, 0 fabricated screenshots; capture success >= 99% |
| Action freshness | monotonic capture-start to proposed input | no action from duplicate/stale frame; report p95 end-to-end |
| Learning | held-out seed/mode transfer, matched budgets | statistically supported win-rate increase over baseline; no hidden-data leakage |
| Game creation | geometry, collisions, console, playtest and human design review | zero critical geometry/physics/console issues on accepted scenes |
| VTuber naturalness | blind human-rated voice + synchronous mouth/head/ear motions | demonstrably better ratings than baseline; p95 spoken-response/FPS regressions absent |
| Speed | same-scene inference + 8 GB game stream | actual p95 TTFT/audio/FPS improvement; no VRAM OOM, no false gains |
| Privacy | local storage/egress audit | no unapproved screenshot, viewer IDs, mic recordings, OAuth or private notes in repo |

## Limitations, merge gates, and public-repo warning

This branch adds a functional **MCP-image-to-GameFrame adapter** with offline fake-MCP tests. It does not enable live screen capture by itself, connect the microphone, start OBS, speak on Twitch, play games autonomously, improve model weights, or prove better game win rates. Validation on an actual Windows Studio instance is required before any live-claim. Keep this as an **unmerged draft stacked on PR #666** until complete offline checks, human review and a real device pilot are green.

The repository `Star-AI-Private` is **public** according to GitHub metadata at research time. Do not upload OAuth tokens, real viewer transcripts, hidden eval seeds, machine IDs, live screenshots, or recordings to it. Secret material belongs only in trusted local stores. No such material is introduced by this branch.
