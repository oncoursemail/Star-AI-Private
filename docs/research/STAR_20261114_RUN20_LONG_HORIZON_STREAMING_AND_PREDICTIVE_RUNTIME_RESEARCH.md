# STAR Run 20 — Long-Horizon Streaming, Predictive Runtime & Transfer-Safe Intelligence

**Research date:** 2026-11-14  
**Target:** existing STAR development stack on `feat/resource-admission-20261113-run21`  
**Scope:** real-time VTuber interaction, resource scheduling, reusable skills, long-horizon gaming/creation, and measurable capability growth.

## Executive decision

STAR should stop treating “smarter” as a larger model or a larger number of agents. The next quality jump should come from **better closed-loop operation**: observe the real environment, choose a bounded action, measure what happened, recover when it fails, and retain only improvements that transfer.

This run adds one small runtime observability improvement and a research-backed integration plan. It does **not** install models, enable external services, add OAuth credentials, or change production defaults.

## Repository facts that constrain the design

The current branch already contains important foundations:

- `star/voice/call.py` has per-turn timing and cancellation, but its `SpeechToText` contract is still one-shot `transcribe(pcm)`.
- `star/voice/room_host.py` is a trusted ingress boundary for final classified cues. Provider SDKs, diarization, ASR, and game observers intentionally remain outside it.
- `star/voice/persona.py` already separates persona wording from the room director's authority to speak.
- `star/resource_planner_service.py` and the lease-based work in PRs #1140/#1142 are the intended resource admission path. Do not add a second scheduler.
- `star/skill_evolution_lab.py` already freezes candidate selection before sealed holdout evaluation. It is a safe foundation, but local task improvement alone is not proof of transfer.
- `benchmarks/roblox` has 20 real-Studio-checked tasks; `docs/GENERAL_KNOWLEDGE_BENCHMARK.md` explicitly describes only ten authored development tasks, not a broad measure of general intelligence.

These boundaries matter: new ASR, game observation, Twitch/YouTube, OBS, and VTube Studio providers should be adapters that submit bounded, authenticated events to existing hosts, not new parallel authorities.

## 1. Runtime performance: predictive demand, not speculative overcommit

### MAPS (arXiv:2609.15359)

MAPS studies memory-aware predictive scheduling for disaggregated prefill/decode serving. It predicts output-length demand, calibrates an uncertainty-aware upper bound, and uses hierarchical scheduling to reduce queue buildup and head-of-line blocking. Its paper reports average end-to-end latency reduction of 42.6% and tail-latency reduction up to 84.8% in its evaluated multi-instance environment.

**STAR adaptation:** use prediction as a *bounded scheduling hint*, never as a reservation guarantee or permission to exceed measured capacity.

1. Record recent input length, output length, task class, model, and actual peak memory for each completed request.
2. Maintain per-model/per-task-class quantiles and confidence coverage; do not use one global average.
3. Estimate demand with a conservative upper bound. If the sample count is too small or the interval is poorly calibrated, fall back to the existing static demand.
4. Feed the estimate to the existing lease/admission controller from #1140/#1142.
5. Preserve hard capacity ceilings and the interactive reserve for audio, game control, and active voice.
6. Defer low-priority research, indexing, training, and asset generation at safe checkpoints; never pause a live audio callback or a partially applied external action.
7. Compare against the static policy under the same workload trace. Reject the predictor if p95/p99 latency, starvation, memory safety, or task success gets worse.

**Do not copy MAPS's disaggregated multi-GPU architecture onto STAR's single 8 GB GPU by assumption.** The transferable idea is calibrated demand prediction and queue discipline, not its cluster topology or reported speedup.

Source: https://arxiv.org/abs/2609.15359

## 2. Voice and streamer realism: score the entire interaction at the client

### InteractionBench (arXiv:2611.02430, 2026-11-02)

InteractionBench evaluates timing, spoken-task accuracy, whisper/volume control, and groundedness over more than twenty turns. It contains 221 items across thirteen scenarios. Its paper reports that timing and spoken-task accuracy are correlated among tested full-duplex systems, and that client-heard timing can differ materially from server-reported timing when network delay is excluded.

**STAR adaptation:** measure the experience at the point where the audience hears and sees it.

- Keep a monotonic event timeline for mic frame, endpoint decision, final transcript, first model token, first complete sentence, first TTS chunk, speaker enqueue, playback start/end, and avatar parameter update.
- Distinguish **speaker enqueue** from **actually audible playback**. The current `first_audio_at` means audio handed to the speaker queue; it is not proof that the audience heard it.
- Score spoken-task accuracy separately from floor-control accuracy: answer correctly, stop when a human resolves the question, stay silent when not addressed, and recover correctly after interruption.
- Test groundedness at 5, 10, and 20+ turns; measure whether she attributes a statement to the correct speaker and remembers what was actually said.
- Keep synthetic audio, model output, chat text, and game events as separate typed sources with provenance. A game event must not be promoted to a human speech cue.

Sources:
- https://arxiv.org/abs/2611.02430
- https://arxiv.org/abs/2609.15759 (streaming transcription head alongside a full-duplex speech model)

### Multiparty and audiovisual evaluation

MP-Bench (arXiv:2609.13076) reports that the tested real-time voice agents reached at most 22% multiparty comprehension and near-chance turn-taking. Duplex-MPE (arXiv:2609.31948) evaluates 2,000 three-/four-person scenarios and explicitly scores when an assistant should answer, remain silent, or stop after a human resolves a request. TurnBench provides 154 dyadic conversations (about 30 hours, 106 speakers) with annotated end-of-turn and interruption events. VideoFDB evaluates 237 audiovisual clips across eleven nonverbal dynamics, separating perception from generation; its dataset is gated under a non-commercial evaluation license.

**STAR adaptation:**
- Add an offline, consented multiparty evaluation set with explicit and implicit addressing, overlapping speech, backchannels, speaker changes, and human-resolution cases.
- Use the existing `RoomStreamHost` contract for final, moderated, source-attributed cues.
- Keep uncertain diarization/addressee results as low-confidence observations; they must not trigger privileged tools.
- Evaluate gaze/attention-like avatar cues only when supported by actual input or an explicit scripted test event. Do not fabricate visual perception or human experiences.
- Do not bundle gated/non-commercial VideoFDB data into STAR or use it for commercial training. Use the paper's evaluation taxonomy to author a separately licensed internal test set.

Sources:
- https://arxiv.org/abs/2609.13076
- https://arxiv.org/abs/2609.31948
- https://github.com/SesameAILabs/turnbench
- https://research.nvidia.com/labs/amri/publication/mazumdar2026videofdb/

## 3. Procedural memory: test transfer, not just local improvement

### AFTER (arXiv:2606.23127)

AFTER evaluates 382 tasks, six professional roles, and 22 procedural skills. It distinguishes local improvement, cross-task transfer, cross-role transfer, and cross-model generalization. The paper reports a 3.7–6.7 point aggregate gain after one refinement round in its tested settings, and better cross-model test accuracy from diverse multi-model traces than single-model traces.

**STAR adaptation:** extend the existing sealed-holdout skill lab with a transfer matrix:

| Evaluation lane | Example |
|---|---|
| Local | Repeat the same Roblox inventory task with a new seed |
| Cross-task | Reuse inventory validation in a shop or crafting system |
| Cross-engine | Transfer a tested design/debugging method from Godot to Roblox where the concepts truly match |
| Cross-model | Execute the same skill with a different model/provider |
| Adversarial | Missing files, changed APIs, malformed state, interrupted tool calls |
| Longitudinal | Re-run a fixed regression suite after several skill revisions |

Every candidate must retain provenance, dependency versions, known limitations, and rollback information. The proposer must not see sealed cases or scores. A skill that improves one benchmark task but harms held-out tasks is rejected or marked narrowly specialized.

Source: https://arxiv.org/abs/2606.23127

## 4. Long-horizon agent evaluation: real tools, state audits, recovery

### WildClawBench (arXiv:2605.10912)

WildClawBench uses 60 human-authored multimodal tasks in native agent runtimes. The paper snapshot describes tasks averaging about eight minutes and more than twenty tool calls, with deterministic checks, environment-state auditing, and semantic judging. The repository's later audited runs report updated scores, so STAR must record the exact benchmark snapshot and harness version rather than treating one score as timeless.

The benchmark also reports substantial harness sensitivity: changing the harness can change a model's score by up to 18 points.

**STAR adaptation:** create a small STAR-owned long-horizon suite rather than immediately importing the full benchmark.

- 10–15 owner-authored scenarios initially, each 5–20 minutes and 15–50 tool calls.
- Cover a Roblox Studio feature, a game-play objective, a research task, a Blender asset pipeline, a knowledge investigation, and a stream moderation/interaction scenario.
- Grade final artifacts *and* intermediate side effects: files changed, process state, tool calls, game state, API calls, permission boundaries, and recovery after tool failure.
- Record the exact model, harness, prompt, tool versions, environment image, and resource policy.
- Run each scenario in an isolated workspace with no production credentials.
- Keep hidden evaluation checks out of the agent-visible task workspace.
- Report completion, correctness, time, tool-call count, recovery rate, unsafe-action count, and resource cost.

Sources:
- https://arxiv.org/abs/2605.10912
- https://github.com/InternLM/WildClawBench

## 5. Game creator: use visual feedback and strict reproducibility

The current official GameDevBench repository states that its Godot benchmark contains **333 tasks**, not 132. Its current README reports later leaderboard updates, including GPT 6 Astra High at 229/333 (68.8%) under Codex with runtime video and strict confinement. Those are external benchmark results, not STAR's score.

**Correction to the previous Run 18 note:** the claim that the canonical GameDevBench contains 132 tasks was incorrect. The official repository currently identifies 333 tasks; remove the 132-task correction from any future summaries. Benchmark snapshots and leaderboard configurations can change, so record the commit, Godot version, harness, and evaluation flags for every comparison.

The benchmark reports that tasks cover 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. Its visual-feedback experiments show that image/video feedback can materially improve task success.

**STAR Creator acceptance loop:**

1. Inspect repository/project state.
2. Plan a bounded change set.
3. Edit in a disposable copy or test place.
4. Run static checks and build.
5. Launch the real engine.
6. Capture structured logs and screenshots/video.
7. Compare against explicit visual/behavioral criteria.
8. Repair one defect class at a time.
9. Re-run the full regression set.
10. Promote only after artifact, runtime, and regression checks pass.

For Roblox, retain the existing real-Studio benchmark and Studio Lab guarded path. For Godot, pin the benchmark's required engine version when comparing to its leaderboard. Do not claim a game is finished because scripts compile.

Source: https://github.com/waynchi/gamedevbench

## 6. General knowledge: distinguish retrieval, reasoning, and demonstrated ability

STAR's existing general-knowledge checker is explicitly a ten-task development suite. It is useful for testing abstention, correction, arithmetic, and structured answers, but it does not establish broad general intelligence.

Add three separate score families:

- **Knowledge:** source accuracy, date sensitivity, contradiction detection, citation coverage, calibrated uncertainty.
- **Reasoning:** multi-step consistency, counterexample handling, unit checking, alternate-solution verification.
- **Execution:** can STAR actually perform the task in a sandbox and pass an independent grader?

A fact should carry source, retrieval date, valid-time interval where known, confidence, and supersession links. A procedure should carry executable evidence and a version. Never turn an unverified model-generated claim into a trusted memory simply because it was repeated.

## 7. Code change in this run: isolate first-audio latency

The existing voice metrics recorded `first_token_at`, `first_sentence_at`, and `first_audio_at`, but reported only the combined `first_token_to_first_audio` interval. That made it harder to tell whether a slow response came from sentence formation or TTS/queueing.

This run adds non-breaking derived fields to `TurnMetrics.stages()`:

- `first_token_to_first_sentence`
- `first_sentence_to_first_audio`
- `transcript_to_first_audio`
- `turn_end_to_first_audio`
- `tts_real_time_factor` (TTS compute seconds divided by synthesized audio seconds)

The existing aggregate fields and latency table remain intact. The metric's first-audio timestamp is explicitly documented as **speaker-queue handoff**, not confirmed audible playback. Regression tests cover the decomposition, absent values, clamped clock differences, and TTS RTF.

This is an observability improvement, not a claim that voice inference is faster. It makes the next hardware benchmark capable of identifying which stage should be optimized.

## 8. Acceptance gates for the next implementation phase

| System | Minimum acceptance |
|---|---|
| Predictive admission | Calibrated demand bounds; no reserve violation; no worse p95/p99 or starvation than static baseline |
| Voice timing | Client-observed first-audible-audio and avatar-sync latency; p50/p95/p99; no hidden server-clock subtraction |
| Multiparty behavior | Correct answer/silence/stop action on explicit, implicit, overlap, backchannel, and human-resolution cases |
| Streaming ASR | Bounded queues; cancellation; partial/final distinction; no stale transcript publication |
| Skill evolution | Sealed holdout plus cross-task/cross-model regression; rollback on regression |
| Game agent | Real environment state checks, action expiry, recovery, and held-out maps/tasks |
| Creator | Static + build + runtime + visual + regression validation |
| General knowledge | Separate knowledge, reasoning, and execution scores |
| Streaming persona | Natural timing and grounded reactions; no fabricated biography or unobserved experiences |

## 9. Source register

1. MAPS — Memory-Aware Predictive Scheduling: https://arxiv.org/abs/2609.15359
2. InteractionBench: https://arxiv.org/abs/2611.02430
3. Streaming transcription in full-duplex S2S models: https://arxiv.org/abs/2609.15759
4. MP-Bench: https://arxiv.org/abs/2609.13076
5. Duplex-MPE: https://arxiv.org/abs/2609.31948
6. TurnBench: https://github.com/SesameAILabs/turnbench
7. VideoFDB (NVIDIA research): https://research.nvidia.com/labs/amri/publication/mazumdar2026videofdb/
8. AFTER procedural memory: https://arxiv.org/abs/2606.23127
9. WildClawBench paper: https://arxiv.org/abs/2605.10912
10. WildClawBench implementation: https://github.com/InternLM/WildClawBench
11. GameDevBench current official repository and leaderboard: https://github.com/waynchi/gamedevbench

## Evidence and deployment boundary

Research claims above are attributed to their own papers or project repositories and are not assumed to reproduce on STAR's hardware. The MAPS results come from a disaggregated serving setup; VideoFDB data has a non-commercial/gated restriction; benchmark scores depend on model, harness, environment, and snapshot. The only runtime code change in this run is additive voice latency instrumentation plus tests. No new ASR engine, model weights, GPU kernel, provider integration, streaming credential, game controller, or production default was installed or enabled.
