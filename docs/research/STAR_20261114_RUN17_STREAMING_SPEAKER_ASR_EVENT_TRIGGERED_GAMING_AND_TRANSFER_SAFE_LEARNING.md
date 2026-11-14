# STAR Run 17 — Streaming Speaker ASR, Event-Triggered Game Control, and Transfer-Safe Learning

**Research date:** 2026-11-14  
**Repository:** oncoursemail/Star-AI-Project  
**Target branch:** feat/resource-admission-20261113-run21  
**Baseline audited:** PR #1178 head 7b284956049789ec1f8471da22ac58fb5efa9970  
**Status:** research and integration specification; no model, provider, or production default changed.

## Executive decisions

This run adds three concrete findings that were not covered by the previous Run 11–16 documents:

1. Microsoft now publishes a streaming, speaker-attributed ASR path, plus a separate CPU-oriented BitNet inference port. They are different deployment products and must not be conflated.
2. Game-agent research now gives STAR a practical event-triggered control policy: reuse a strategic plan while the world remains stable, keep a fast reactive controller active, and spend expensive reasoning only at meaningful events or failures.
3. New game-evaluation evidence shows that reflection can improve a practiced map while failing to transfer to variants, and can regress after its best round. STAR must preserve the best verified skill checkpoint and require held-out transfer before promotion.

The recommendation is to extend the existing STAR interfaces and evaluation harnesses. Do not add a second voice pipeline, resource scheduler, task ledger, or skill store.

## 1. Streaming speaker-attributed ASR: VibeVoice is now a real candidate

### 1.1 Streaming model

Microsoft's VibeVoice-ASR-Streaming technical report describes fixed-size audio chunks, limited lookahead, and previous transcript context. It emits speaker-attributed text while audio is still arriving, rather than waiting for the entire recording. The published model supports ten languages and customized hotwords.

Sources:
- Microsoft Research technical report: https://www.microsoft.com/en-us/research/publication/vibevoice-asr-streaming-technical-report/
- Streaming implementation guide: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr-streaming.md
- Official model card: https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-7B
- Technical report: https://arxiv.org/abs/2609.02812

Important hardware boundary: the inspected official Streaming-7B model card reports **9B total parameters in BF16**, despite the checkpoint's 7B name. The official quick-start uses an NVIDIA PyTorch container and optionally FlashAttention. This is not a sensible default for STAR's 8 GB RTX 4060, and no local fit or latency should be assumed. The model card identifies the project as MIT-licensed; pin the exact code and weight revisions if it is ever evaluated.

### 1.2 Separate CPU candidate: VibeVoice-ASR-BitNet / VibeASR.cpp

Microsoft also publishes VibeASR.cpp, a separate CPU-oriented runtime for VibeVoice-ASR-BitNet.

Its repository reports:
- 1.58 GB quantized model files, compared with 4.62 GB for its FP16 counterpart.
- Heterogeneous quantization: I8_S VAE and I2_S language-model weights with Q6_K embeddings.
- Vendor-reported real-time factor below 1 on three or more CPU threads in selected x86/ARM tests.
- A Windows 11 Intel Core i7-13700 benchmark, with reported RTF 0.43 at three threads.
- The README overview describes roughly 1–4 absolute WER points of degradation, but the published table is dataset-dependent and includes larger gaps (for example, +7.62 points on AISHELL4 and +4.37 on AliMeeting versus the listed 7B reference). Use the per-dataset table, not the overview range, when setting acceptance thresholds.
- Seven listed languages in the model card, with accuracy varying by language and corpus.

Sources:
- Official runtime: https://github.com/microsoft/VibeASR.cpp
- Official model card: https://huggingface.co/microsoft/VibeVoice-ASR-BitNet
- Technical report: https://arxiv.org/abs/2607.21075

**Critical distinction:** the inspected VibeASR.cpp usage exposes file-based CLI inference and a Gradio demo; its README does not document the streaming chunk/session API used by VibeVoice-ASR-Streaming. Treat BitNet as a compact CPU transcription candidate, not as a drop-in streaming replacement. Its vendor RTF figures exclude one-time model loading and were not measured on STAR's CPU. CPU inference may also steal cycles from the game, desktop, or local model.

### 1.3 STAR integration design

Keep STAR's existing ASR engine interface and call lifecycle. Add optional provider adapters only after a paired local benchmark.

Required event flow:

1. Capture consented microphone frames.
2. Run VAD and maintain a bounded utterance/session clock.
3. Feed each audio chunk once to a true streaming backend where supported.
4. Publish partial transcript revisions with monotonically increasing utterance and revision IDs.
5. Associate speaker labels with opaque, session-scoped IDs; never infer a real-world identity from a voice.
6. Run addressee/intent classification separately from diarization. Knowing who spoke does not establish that the speaker addressed STAR.
7. Convert only trusted, sufficiently classified events into the existing RoomCue/RoomStreamHost contract.
8. Commit only finalized transcript text to conversation history. Partial hypotheses may guide cancellable preparation but must not trigger tools, external actions, or durable memory.
9. Invalidate every outstanding partial result when the utterance, call, or stream generation changes.

The existing room director remains the authority for whether STAR speaks. ASR and diarization provide evidence; they do not grant the floor.

### 1.4 Required ASR comparison

Compare the current Faster-Whisper path, the already-researched NeMo-Speech.cpp path, VibeVoice-ASR-Streaming where hardware permits, and VibeVoice-ASR-BitNet as a final-transcription/CPU candidate.

Use the same consented, locally stored evaluation clips and the same ground-truth transcript. Record:
- WER/CER by language, speaker count, noise level, and overlap.
- First partial latency and first stable-partial latency.
- Revision count and the fraction of words later retracted.
- Finalization latency and missed/false end-of-turn rate.
- Speaker-attribution accuracy and addressee-classification accuracy separately.
- Real-time factor, model-load time, resident RAM/VRAM, CPU threads, and GPU memory.
- Concurrent STAR model tokens/second, game frame-time p95, audio underruns, and OBS dropped frames.

Run CPU thread sweeps (1, 2, 3, 4, 6, 8) where supported. Do not use every CPU core by default. A speech backend that reaches RTF < 1 in isolation but causes game stutter or delayed chat under mixed load is a failed STAR configuration.

## 2. Event-triggered dual control for game playing

### 2.1 SPIKE: reuse strategy, react locally, escalate at events

SPIKE proposes a strategic controller that performs low-frequency planning and recovery, paired with a reactive controller that executes local actions under a tight token/latency budget. An event trigger monitors visual change, objective progress, repeated actions, and failure signals. Its reported results are benchmark-specific and are not a promised STAR speedup.

Source: https://arxiv.org/abs/2605.18636

STAR already has multi-horizon Gamer Brain research. The new implementation detail is to make escalation event-driven and measurable rather than scheduling strategic reasoning at a fixed interval.

Recommended controller contract:

- **Strategic plan:** goal, ordered subgoals, expected state, preconditions, resource budget, expiry, and recovery branch.
- **Reactive controller:** short-lived movement/camera/input actions; it never blocks waiting for the strategic model.
- **Event monitor:** objective progress, scene transition, health/resource threshold, repeated no-progress actions, death/respawn, unexpected enemy, invalid input, timer boundary, or confidence drop.
- **Plan validator:** checks current observation against plan preconditions before every action batch.
- **Escalation:** ask the strategic model to replan only when a meaningful event invalidates the current plan or when the reactive controller detects a bounded failure loop.

An old plan may be reused only while its preconditions remain true. Each action must carry an observation sequence, action generation, deadline, and expiry. A new observation, cancellation, death, scene change, or expired deadline invalidates stale actions.

### 2.2 Text bridge before latent bridge

The Latent Bridge project explores passing a slow reasoning model's hidden-state information to a fast reactive model through a small learned adapter. Its public experiment uses roughly 8–9B models and a 33.6M-parameter bridge; the authors report task-dependent gains, not a universal advantage.

Sources:
- Paper: https://arxiv.org/abs/2606.24470
- Reproducible project: https://github.com/19PINE-AI/latent-bridge-games

STAR should not attempt to reproduce this on its 8 GB GPU now. First establish three baselines on the same held-out tasks: fast-only, slow-only, and fast-plus-text-plan. Only if the text-plan bridge reliably beats fast-only on a task family should STAR consider a learned latent bridge. Hidden-state access, model compatibility, training data, and memory footprint are substantial prerequisites. Never combine text and latent channels without a separate ablation; the project reports destructive interference in some configurations.

## 3. Evaluate actual game learning, not only first-attempt skill

### 3.1 OmniGameArena

OmniGameArena provides twelve Unreal Engine 5 games across solo, PvP, and cooperative play, with one original map and four variants per game (60 maps total). Its agent runner accepts remote input; the Windows environment archive is approximately 2.72 GB. The environment and runner are separate downloads, so this should be an optional benchmark adapter, not a bundled STAR dependency.

Sources:
- Project and protocol: https://mxlin043.github.io/OmniGameArena/
- Runner code: https://github.com/mxlin043/OmniGameArena
- Environment/data card and SHA-256 checksums: https://huggingface.co/datasets/mxlin043/OmniGameArena
- Paper: https://arxiv.org/abs/2606.09826

Its two evaluation clocks matter:
- **LFM:** pause the game while the model thinks; isolates decision quality.
- **LCM:** charge inference time to the game clock; measures real-time play.

Use both, but use LCM for any claim about real-time gameplay. LFM must never be presented as proof that STAR can act quickly enough in a live game.

### 3.2 Reflection can overfit and regress

OmniGameArena reports that, across 72 improvement curves, 42 reached a best round more than 0.1 above cold start. However, ten of those rising curves ended more than 0.1 below their own best round. Learned skills gained an average 0.19 on the practiced game but only 0.03 on variants; two of five variant cells were below their corresponding cold-start score. The gain on the practiced game explained only about a tenth of the variance in transfer.

This is a strong warning against promoting the newest or most recently self-authored skill.

### 3.3 STAR skill-promotion protocol

For each skill candidate:

1. Freeze a baseline skill and record the exact model, prompt, tool, game, and harness revisions.
2. Run cold-start episodes on a preregistered development set.
3. Allow bounded practice/reflection rounds. Every round writes a versioned candidate; it cannot overwrite the baseline.
4. Score every round on the development set and retain the best checkpoint, not automatically the final checkpoint.
5. Evaluate the selected checkpoint on unseen seeds, maps, mechanics, and game variants that were not used for reflection.
6. Compare against the frozen baseline with the existing paired evaluator and uncertainty gates.
7. Promote only when the preregistered transfer gate passes and no protected capability regresses.
8. Keep rollback metadata and the prior skill version. If transfer is inconclusive, keep the old skill.

Use OmniGameArena for broad visual game behavior, OpenGameEval for Roblox Studio editing/Play-session tasks, and GameDevBench for game-creation tasks. These are different capabilities and must retain separate scorecards.

### 3.4 Embodied compositional learning

EmbodiedCLBench evaluates whether agents can learn simpler embodied tasks and recombine the resulting skills to solve unseen, more complex tasks. Its authors report that distilled skill summaries can help, but more accumulated examples do not automatically produce proportional gains.

Sources:
- Paper: https://arxiv.org/abs/2610.13021
- Official benchmark: https://github.com/PKU-VaLuE-Lab/EmbodiedCLBench

STAR should build a curriculum of small verified primitives (navigate, collect, craft, equip, defend, build, repair) and test their composition on unseen task combinations. Compare three conditions: zero-shot, relevant raw history in context, and a distilled skill summary. This measures whether the skill itself carries reusable information instead of merely benefiting from a longer prompt.

## 4. More natural streaming: fuse the room timeline, not just the transcript

LiViBench studies interactive livestream understanding across 24 tasks and combines audio, speech, and real-time comments. Its dataset card is CC BY-NC 4.0, so STAR must not bundle or use that dataset in a commercial distribution without separately resolving the license. The paper's evaluation design can still inform STAR's own consented, owner-created rehearsal set.

Sources:
- AAAI paper: https://ojs.aaai.org/index.php/AAAI/article/view/39859
- Dataset card: https://huggingface.co/datasets/Xiaodong/LiViBench

Recommended Social Director inputs are time-aligned events, not one giant prompt:
- final/partial speech transcript with revision and speaker IDs;
- chat messages with platform event IDs and timestamps;
- compact game-state events and objective changes;
- optional low-rate or event-triggered visual observations;
- current playback generation and actual played-time receipt;
- moderation, consent, and source-allowlist results.

The director should prioritize direct questions, meaningful game events, unresolved conversation turns, and safety/moderation events. Viewer-to-viewer conversation should usually remain uninterrupted. A game event should not trigger commentary merely because a frame changed; it should be salient, grounded, and appropriate for the current speaking floor.

For visual context, prefer event-triggered keyframes and short bounded clips over continuous high-rate screenshot submission. Keep timestamps, source, confidence, and evidence references attached to each observation. Do not infer viewer identity or private attributes from video/audio.

## 5. Repository integration map — extend the existing stack

The current repository already has relevant draft work. These are integration targets, not shipped capabilities:

| Existing work | Reuse for this run |
|---|---|
| #1140 / #1142 | Single lease-based resource authority and stream-pressure governor |
| #1152 / #1153 | Trusted, coherent host telemetry |
| #1160–#1164 | Stable partial-prefix preparation and resource-calibrated admission |
| #1165 / #1166 | Rehearsal quality gates and paired revision evaluation |
| #1167 | First-content and streamed-token benchmark |
| #1108 / #1121 | GameDevBench creator evaluation and cached skill retrieval |
| #1109 / #1117 | Continual-learning transfer and governed memory consolidation |
| #1168 | Existing real-time intelligence and game architecture blueprint |
| #1171–#1178 | Room director, cue queue, payload store, call dispatch, trusted host, durable coordination, and natural streamer behavior |

Do not add:
- a second resource scheduler;
- a second task or memory ledger;
- a separate room director;
- a second speech playback pipeline;
- a new game-skill store that bypasses the existing skill/versioning and paired-evaluation work.

### Priority implementation sequence

**P0 — Reproducible speech bake-off**
- Add pinned optional benchmark recipes for Faster-Whisper, NeMo, VibeVoice streaming, and VibeVoice BitNet.
- Record model/code checksums, license, exact CPU/GPU backend, and memory.
- Keep model downloads opt-in and outside the installer.
- Measure ASR and mixed-load performance on the actual target PC.

**P1 — One streaming ASR adapter**
- Add a provider-neutral streaming session interface behind the existing engine registry.
- Support partial revisions, finalization, cancellation, bounded queues, timestamps, and speaker metadata.
- Keep addressee detection separate from diarization.
- Keep partials ephemeral and final transcripts canonical.

**P2 — Event-triggered Gamer controller**
- Add event types and plan-precondition validation to the existing game event/control path.
- Reuse reactive actions while the plan remains valid.
- Escalate on objective changes, state transitions, stuck loops, failure, or plan invalidation.
- Keep action expiry and observation-generation checks mandatory.

**P3 — Transfer-safe skill learning**
- Add an improvement-curve report to the existing paired evaluator.
- Retain the best candidate checkpoint and compare it to the frozen baseline.
- Use sealed map/seed/variant holdouts for promotion.
- Report original-task gain and transfer gain separately.

**P4 — Stream event timeline**
- Align speech, chat, game, visual, and playback receipts on one session timeline.
- Keep event payloads short-lived and bounded.
- Use the existing room director for floor control and the existing delivery ledger for audible-output evidence.

## 6. Acceptance gates

### Speech
- WER/CER and speaker attribution reported separately.
- First stable partial and finalization p50/p95.
- Partial revision/retraction rate.
- False end-of-turn and missed-turn rates.
- No stale partial transcript may publish after generation invalidation.
- Under mixed load, no protected audio/game QoS regression beyond preregistered tolerances.

### Gameplay
- LCM completion/success is the real-time headline metric.
- Report LFM separately as decision-quality-only.
- Report p50/p95 action age, stale-action rejection, invalid inputs, game frame-time p95, and recovery after failure.
- Require held-out variant/seed transfer before skill promotion.

### Streaming
- Measure false interruption, missed direct questions, addressee accuracy, response delay, and duplicate/obsolete replies.
- Verify that chat, audio, game cues, and playback state are correctly aligned.
- Do not optimize for more speech or more viewer engagement at the expense of turn-taking quality, privacy, or stream stability.

### Intelligence and learning
- Report cold-start, best-practice, final-practice, and held-out-transfer scores separately.
- Keep model/prompt/tool/harness revisions fixed within paired comparisons.
- A skill is not "learned" merely because the model can explain it; it must execute successfully on unseen variants.

## 7. Capability roadmap beyond streaming and games

Once the shared runtime is reliable, STAR can extend the same evidence-and-skill pattern to:
- general research with claim-level citations, source dates, contradiction tracking, and uncertainty;
- structured tutoring with generated exercises and independently scored mastery;
- game creation across Roblox, Godot, Unity, and Blender with build/play/visual regression loops;
- art, animation, VFX, sound design, and asset-pipeline skills;
- project management with durable checkpoints, dependency tracking, and rollback;
- stream production assistance such as owner-reviewed highlight markers, chapter drafts, and scene suggestions;
- cross-game skill transfer and practice arenas;
- owner-approved integrations for Discord, Twitch, YouTube, OBS, and VTube Studio.

These remain proposed extensions until the corresponding provider, permission, host, and hardware acceptance tests pass.

## 8. Safety, privacy, and identity boundaries

- Keep microphone, chat, screen/video, and platform ingestion opt-in with visible session state.
- Use opaque, session-scoped speaker IDs; do not attempt real-world voice identification.
- Do not store raw audio/video/chat by default. Retain only the minimum event metadata and owner-approved memories.
- Keep platform tokens in the existing credential store; never put them in prompts, logs, model context, or Git.
- Treat all viewer text and game content as untrusted input.
- Preserve STAR's AI-character transparency. Natural timing, humor, listening, and consistent character voice are desirable; fabricated human biography or claims of real human experience are not.
- Keep high-risk external actions behind owner approval and make cancellation/revocation immediate.

## 9. Source and applicability summary

| Research | What STAR should take | What STAR should not assume |
|---|---|---|
| VibeVoice-ASR-Streaming | Chunked speaker-attributed transcript architecture | That the 9B BF16 checkpoint fits an 8 GB GPU |
| VibeVoice-ASR-BitNet | CPU memory/throughput candidate for final transcription | That its file inference path is streaming |
| SPIKE | Event-triggered strategic escalation and reactive override | That paper speedups transfer to STAR hardware |
| Latent Bridge | A later slow-to-fast communication experiment | That a 33M bridge and two 8–9B models are practical on STAR's current GPU |
| OmniGameArena | Real-time clock, improvement curves, variant transfer | That one practiced-map gain proves general game mastery |
| EmbodiedCLBench | Skill composition and unseen-task transfer | That more examples always improve the agent |
| LiViBench | Audio/speech/chat/video event alignment | Permission to bundle its CC BY-NC dataset in a commercial release |

## 10. Run 17 conclusion

The highest-value next step is not another model swap. It is a reproducible speech bake-off, followed by one provider-neutral streaming ASR adapter, event-triggered game control, and transfer-safe skill promotion—all connected to the existing room, resource, task, delivery, and evaluation infrastructure.

The most important learning lesson is to keep the best verified checkpoint, not the latest self-written one. The most important streaming lesson is that diarization is not addressee recognition. The most important performance lesson is that an isolated real-time factor is not enough: STAR must remain responsive while voice, game control, inference, OBS, and background work are all active.

No runtime code, model weights, installer contents, production defaults, or platform credentials were changed in this research run.
