# STAR: Connected Multi-Game Intelligence, Real-Time Performance, and Natural VTuber Research
**Date:** 2026-10-27
**Classification:** implementation plus researched experiments; offline-first, default OFF.
**Stack:** Python STAR backend, private Roblox Studio playtests, local Star Core Forge, optional GitHub draft export.

## 1. The engineering bottleneck found in this run

STAR had BOTH a fair multi-game practice selector (`GamePortfolioPractice`) and a real, independently evaluated, private-Studio input path (`StudioPracticeRunner`). But the two were not joined by a tested trust boundary. The scheduler minted a random, expiring `apr_...` practice run ID. The runner independently obtained a ladder recommendation and used a separately constructed `GameScope.episode_id`.

Without a common host-enforced binding, a future orchestration could accidentally:
- Execute an action in the wrong episode, game, version or objective.
- Pick a different action after the portfolio reserved one.
- Record valid signed practice outcomes to a different reservation.
- Continue reasoning after the owner withdrew the reservation, then dispatch a now-unwanted input.
- Report success for a key pulse, or allow a validation result to leak into routine practice.

This is a **closed-loop integration defect**, not a lack of yet another giant foundation model. An agent cannot accumulate reliable autonomy if its hands, eyes, curriculum and evidence ledger disagree about which action was taken.

### Implemented here

1. `GamePortfolioPractice.matches_reservation` now checks the entire scheduler-issued offer (game, version, objective, situation, action, difficulty, ticket, run ID) against its internally held live reservation. It advances expiration and fails closed after disable/restart.
2. `StudioPracticeRunner.take_step` adds a trusted, optional `dispatch_guard` checked after model deliberation and immediately before requesting a physical input permit. Existing callers are unaffected.
3. New `PortfolioStudioBridge` binds one portfolio offer to one fresh private Studio runner with matching `GameScope.episode_id`, expected ladder object, and the *same* signed gameplay evidence bank.
4. Its restricted proposer rejects suggestions if the curriculum has drifted from the reserved action and situation. The underlying runner still checks visual freshness, playing Studio, private focus, telemetry, permitted keys, duration, key release and the one-delivery-at-a-time gate.
5. Independent post-action observations may be passed to a separate evaluator. A validated, host-signed practice trial must match the reserved game/version/objective/situation/action/run before it can complete the portfolio offer.
6. A false/forged signature, missing evidence, abandoned action, stale reservation or leaked validation case never becomes a verified improvement. Practice failure itself remains valid learning data **only** when independently signed.
7. New fake-Studio integration tests exercise real coordinator interactions from reservation through key down/up, changed screenshots, transition SHA-256, independent HMAC, ledger ingest and next-game scheduling. No account or game window touched.

**Important limitation:** the adapter does not install any models, provide a Windows keyboard watchdog, magically make Roblox a playable game, or prove the observer/signer is honest. Keep host-owned physical key-up release and driver-level focus revocation independent of Python. There remains a small race if an independently mutated scheduler session is revoked *after* the last dispatch guard but before physical input; the lower-level Studio host must provide authoritative STOP as designed. The guard narrows—not mathematically eliminates—that window.

## 2. The actual gaming brain STAR should build

A good architecture is **three speeds plus independent proof**, not a single slow model processing every frame.

| Track | Cadence | Input | Output | Correctness rule |
|---|---|---|---|---|
| Reflex | event/30-60Hz host loop | collision, health, state/action mask | bounded navigation/pulse | pre-authorized local game controller only |
| Perception | adaptive 1-5Hz, faster on novelty | fresh video frames, game state, audio | structured hypotheses + confidence | screenshot digest, timestamp, game ID |
| Reasoning | asynchronous 0.2-2Hz when safe | verified observations and task objectives | plan or next experiment | no direct unsanctioned physical input |
| Practice | offline only | signed attempts, skill-bank summaries | new curriculum challenge | evidence receipt, independent grader |
| Validation | separate sealed holdout | unseen seeds/levels from trusted scorer | aggregate transfer verdict | no self-scoring, no training leakage |

The figures above are **initial experiment ranges**, not measured performance on STAR hardware. The host should adjust cadence based on VRAM headroom, game FPS, speech backlog and task deadlines.

### Skill loops to implement on private Brain 2 first

**Obby:** identify platforms/checkpoints -> issue one whitelisted jump/move -> observe changed frame -> independently score survival/progress -> store verified reward and the failure type. Test on *new geometry*, not only memorized coordinates.

**Racer:** identify safe lane, turn timing and obstacle type -> choose one bounded steering primitive -> verify lap/checkpoint delta -> evaluate held-out tracks. Train counterexamples where an aggressive shortcut collides.

**Combat sandbox:** observe cooldown/ammo, range and target position -> choose one approved action -> independently score hit/avoidance. Keep competitive online or other players' gameplay out of automated control until separately allowed by game rules.

**Builder:** inspect affected DataModel objects before editing -> predict hierarchy/geometry changes -> generate controlled Luau/Blender work -> check attachments, scale, object locations, clipping, UV/material seams -> run Studio playtest -> compare screenshots and outcomes. Differentiate valid playability from aesthetic approval.

**Social play:** operate transparently as an AI; do not fabricate an offline friendship, player identity, or a victory that no scorer observed.

### Research basis

- Roblox announced Studio's built-in MCP and playtesting flows on **March 5, 2026**; the April 9 Playtest Agent beta can spawn a simulated test character and validate common interactions. This is a first-class path to real playtest state, not mere code completion.
  - https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
  - https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- Roblox's April 15, 2026 Studio agentic write-up explicitly describes closed plan/build/test/revise workflows.
  - https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- **OpenGameEval (October 1, 2026)** evaluates 13 frontier models on 84 annotated tasks with executable scene and simulated-play checks. The association of inspecting changed objects before editing with higher success motivates an observation-first gate.
  - https://arxiv.org/abs/2610.02563
  - https://github.com/Roblox/open-game-eval
- DeepMind's SIMA 2 work (November 2025) shows directions for interactive world transfer and learning from trial and error, but it does not furnish STAR with the same model, training or capability.
  - https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## 3. Make STAR genuinely faster rather than merely lighter on paper

Optimize **time to useful, audible, verified answer** and **stable game FPS**, not raw tokens per second in isolation. A smaller output that never reaches the speakers is not useful.

**Baseline first:** record 60-second segments of game FPS p10/p50/p95, CPU per process, available VRAM, p50/p95 first audible speech, end-to-end useful response completion, visual assessment cost and interrupted-turn cleanup. Three repetitions per workload with model/driver/quantization hashes.

**Resource partition:** reserve GPU VRAM for game rendering and avatar; push TTS to CPU only if it sustains natural sound and acceptable first-audio times. Heavy models and background practice should refuse admission during live streaming. Existing `StreamVisionHost` worker quarantines must remain active when a GPU callback is canceled.

**Model routing:** low-risk brief speech goes through a fast route only after quality checks; difficult coding/game design uses a stronger model plus verification. Preserve source/cached context around stable system prompts. Test retrieval caching by whether answers on *new* questions actually improve.

**Speculative decoding:** benchmark matched tokenizer draft/target or self-speculative features only if memory fits and measured performance wins against a plain baseline. llama.cpp's SPEED-Bench reports latency, throughput and draft acceptance on a running `llama-server`. Its issue tracker also documents configurations where speculative decoding was *slower*. Do not deploy from marketing claims.
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/10664

**CPU voice:** Kyutai Pocket TTS is a CPU-oriented, streaming TTS candidate. On October 20, 2026 its small-model family was reported to include experimental tiny variants. Prefer official release metadata and voice-quality A/B listening before adopting a specific checkpoint, check model licenses and avoid cloning unconsenting real voices.
- https://github.com/kyutai-labs/pocket-tts
- https://kyutai.org/blog/2026-01-13-pocket-tts

**Admission policy:** gameplay/audio is P0; immediate viewer turn P1; game vision P2; offstream research P3; autonomous training P4. Priority preemption should cancel *workers physically*, not just mark futures canceled; quarantine workers with uncertain GPU state.

### Proposed promotion gates, not current results

- End-to-end p95 spoken reply not worse than the prior pinned build at equal completion rate.
- No more than 1% absolute regression in successful conversational turns.
- Game FPS p10 >= the pinned baseline minus a predeclared tolerance (suggest 3 FPS).
- No increase in leaked/live background practice, stale worker receipts or stuck audio.
- For new game expertise, independently verified gains on sealed unseen levels across *multiple different games*, with all failed/incomplete attempts counted.
- Roll back automatically in local Star Core Forge if any safety/integrity gate fails. Export to GitHub only as an auditable draft.

## 4. Human-natural VTuber without pretending to be a human

STAR should be a consistent, expressive **AI character**—not an undisclosed human impersonation or a model announcing emotions it cannot establish. Give her distinct *character lore*, recurring interests, casual curiosity, running jokes, quiet focus and authentic verified gaming memories.

**Turn hierarchy:** owner stop -> gameplay danger -> explicit viewer question -> short empathetic acknowledgement -> ambient optional. Never talk continuously. A 10-second silence during a hard boss fight can be more human-natural than repeated synthetic celebration.

**Overtalk handling:** VAD alone hears an input, not an intentional interruption. Detect short backchannels ("yeah", "mhm"), true viewer corrections, mic noise and speech overlap; abort/resume playback according to actual audio state. LiveKit documents adaptive interruption approaches, but hosted models may have runtime/cost dependencies; STAR can benchmark local VAD/turn classification with no reliance on paid cloud services.
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/

**Expressiveness:** coordinate confirmed audible phonemes, smiles, brows, eye dart, blink and hair/body spring motions. Trigger gameplay surprise only after verified event; never animate an unspoken achievement. Make the cat/puppy modes opt-in, and respect reduced-motion settings. VTube Studio's public API documents custom parameter inputs for Live2D mapping:
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Speech texture:** train/evaluate small phrasing variation and well-timed hesitation (within content quality constraints), but do not inject random fake breathing, laughter or fabricated backstories. A genuine spoken correction ("I thought that was a checkpoint, but it wasn't") should be grounded in newly verified game state.

**Viewer privacy:** Twitch text is untrusted. Moderate before sending to the model, keep viewer identity out of public long-term knowledge, require fresh session gating after reconnect and measure audible completion rather than message ingestion counts. Consent and platform policy still govern persistent chat memory or streaming.

## 5. Extend general knowledge without pretending model weights changed

Existing `KnowledgePracticeHost` and `KnowledgeRecallPlanner` coordinate evidence-gated learning, not gradient updates or new model weights. Turn approved resources into small independently graded trials, source version digests and age/expiry. Separate study questions from held-out tests. For general knowledge quality, evaluate:
1. Answer correctness on unfamiliar questions;
2. Calibration when evidence is missing;
3. Citation/source recency (especially time-sensitive claims);
4. Retrieval speed and token budgets;
5. Transfer from known concepts into unfamiliar tasks;
6. Resistance to prompt injection embedded in a page, game billboard or chat;
7. Long-term answer stability after restart.

For game creation, retrieval should pull reliable Luau API, Rojo/Wally project patterns, official Blender docs, verified scenes and owner-approved visual references, *then* check in Studio and screenshots. Retrieval alone is not creative skill.

## 6. Local autonomous improvement via STAR Core Forge

Local Forge should own change history, experiment manifests, expected performance targets, signed test summaries, canary switches and rollback checkpoints. GitHub is a secondary publication/review mirror.

Separate three roles:
- **Proposer:** Star or worker agent makes a candidate change, artistic design, lesson or play action.
- **Verifier:** independent sandbox/static analyzer, Studio playtester, holdout scorer or a human critique judges it.
- **Promoter:** trusted local release host confirms evidence and owner policy before activation; no unreviewed model output runs with full PC privileges.

Give STAR a challenge generator with progressively harder *but independently solvable* levels. Refuse training when evaluator capacity is missing; revisit failures as structured diagnosis rather than infinite self-retry. Keep a risk budget for self-modification: any kernel, authentication, spending, publishing or irreversible action remains gated by existing owner policy.

## 7. Concrete acceptance checklist for Brain 2

1. Start a dedicated private Roblox Studio playtest on Windows; confirm Studio instance ID, game/version and owner-enabled focus/input watchdog.
2. Reserve a multi-game practice action from trusted scheduler; instantiate a fresh GameScope whose episode ID equals the scheduler-issued run ID.
3. Construct the existing observer/QoS/actions/outcome/runner with that exact identity; enable each only through its existing host controls.
4. Bind through `PortfolioStudioBridge`; invoke one symbolic model proposal, never unbounded key strings or arbitrary shell.
5. Verify a genuine changed screenshot after the action; have an independently trusted scorer return a signed Practice GameTrial with the exact transition digest.
6. Record once through the bridge. Inspect the next game's scheduled offer and confirm there is **no** result for a wrong run, old scene, holdout split or invalid signer.
7. Repeat with forced disabled portfolio while the model proposes, lost focus, no GPU headroom, live streaming, speech overload, stale screenshots, key-up failure and deliberate recorder crash.
8. Hold back unseen level seeds and publish only aggregate metrics of game transfer; no identities, full images, signing keys or hidden answers in the GitHub PR.
9. Replay identical tests on new Star hardware; compare Windows audible-speech p95, game FPS and GPU memory before promoting.
10. Record failures and approvals in local Star Core Forge, with PR as draft **only** until independent review.

### Implemented vs researched: precise status

**Implemented and unit/integration tested in this change:** tightly scoped active reservation check, post-inference dispatch guard, portfolio-to-Studio coordination, independent signed outcome finishing, fake-Studio adversarial tests.

**Not installed or demonstrated here:** models/fine-tuning, CPU TTS, LiveKit/VTube Studio plugins, actual Roblox Windows play, game FPS or inference-speed gain, real consciousness, unrestricted game access or an OBS live broadcast.

This distinction is intentional. Stronger intelligence requires measured capability gains; realistic expression requires experienced content, not merely an avatar moving.
