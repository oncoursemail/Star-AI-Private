# STAR Run 16 — Multi-Horizon Gameplay, Interaction Alignment & Runtime Reliability

**Research date:** 2026-11-13  
**Repository:** `oncoursemail/Star-AI-Project`  
**Branch:** `feat/resource-admission-20261113-run21`  
**Scope:** new research transfer, one verified source-code reliability fix, and measurable integration gates.

> This document separates published research, repository observations, proposed experiments, and shipped capabilities. A paper, benchmark, draft PR, or green documentation workflow does not mean STAR has acquired the capability.

## Executive findings

The next meaningful improvement to STAR is not another collection of named agents. It is a shared runtime that can keep three time horizons coordinated:

1. **Fast reaction:** bounded, low-latency control and immediate conversational turn handling.
2. **Medium-horizon execution:** a sequence of actions that completes a subgoal.
3. **Long-horizon strategy:** goals, plans, skill selection, and recovery across a complete game or project.

New evidence from GameHorizon gives STAR a concrete way to evaluate these horizons. New EMNLP 2026 research gives a more complete interaction objective for natural full-duplex conversation. The Agent Memory Leaderboard's Cycle 2 specification offers useful governance and evaluation dimensions for textual, coding, multimodal, and streaming memory.

A source audit also identified a specific race in asynchronous voice previews: a slow partial ASR worker can finish after its utterance has ended and publish an obsolete caption. This run fixes that race with a per-utterance generation token and adds a deterministic regression test.

## 1. New research: GameHorizon multi-horizon gameplay

**Primary source:** https://gamehorizon-suite.github.io/  
**Paper:** https://arxiv.org/abs/2609.25001

The official project describes three levels of gameplay instruction:

- **L1 — short-horizon operations:** immediate operations and action sequences.
- **L2 — medium-horizon goals:** a coherent local objective assembled from operations.
- **L3 — long-horizon strategies:** plans that connect multiple goals over a longer game trajectory.

The project page describes 5,000 hours of gameplay across 21 game titles, with temporally aligned videos, actions, and multi-horizon instructions. Its benchmark is described as thousands of offline MCQs plus 20 online tasks and 62 verifiable subtasks. The page currently marks the Hugging Face dataset as coming soon; STAR must not assume that the full dataset is downloadable or licensed for training.

### STAR application: hierarchical Gamer Brain

Use one shared game-state record and three coordinated decision horizons:

| Horizon | STAR responsibility | Runtime constraint | Example |
|---|---|---|---|
| Reflex / L1 | Movement, camera, jump timing, dodge, aim correction | Must not wait for a large model | Keep moving while a plan is computed |
| Tactical / L2 | Complete the next local objective | Bounded action batches with observation checks | Reach cover, collect a key, finish a round |
| Strategic / L3 | Choose route, resource policy, team plan, progression | Can use slower reasoning and tools | Decide how to prepare for a boss or win condition |

The model should not emit an unbounded sequence of keystrokes. Every action batch should include:

- observation timestamp and state/version;
- intended target and expected postcondition;
- maximum action duration or step count;
- cancellation token;
- expiry/deadline;
- permitted input set;
- completion or failure evidence.

Before the next batch, compare the current observation with the expected state. Reject stale actions, re-observe, and re-plan. The fast controller may continue only within a pre-approved, bounded policy while strategic reasoning is pending.

### STAR evaluation transfer

Create local, deterministic tasks with separate scores for:

- L1 control correctness and reaction latency;
- L2 subgoal completion and recovery;
- L3 strategy quality and long-horizon success;
- invalid/stale action rate;
- action age at execution;
- retries, deaths, resets, and time-to-completion;
- transfer to held-out maps, seeds, mechanics, and genres.

Use GameHorizon as a design reference now; evaluate against its official data only when the dataset, license, and execution protocol are actually available.

## 2. Keep game benchmarks complementary

### GameDevBench

**Official repository:** https://github.com/waynchi/gamedevbench  
**Project paper/site:** https://sethkarten.ai/papers/gamedevbench.html

The current repository describes 333 Godot tasks across gameplay logic, UI, 2D graphics/animation, and 3D graphics/animation. Its README specifies Godot 4.4.1 for comparable official runs. The repository's current results section includes newer leaderboard entries than the original paper's initial results; STAR should record the exact benchmark commit, agent harness, model, and tool configuration with every comparison.

The central transfer is visual feedback. Game development is not only code generation: screenshots or video, scene state, runtime behavior, and asset correctness are part of the task. A correct script can still produce a broken scene.

### OpenGameEval

**Official repository:** https://github.com/Roblox/open-game-eval  
**Paper:** https://arxiv.org/abs/2610.02563

Use it for Roblox Studio-specific exploration, editing, and Play-session validation. Keep observation and mutation tools distinct. A Roblox Studio result must not be reported as a Godot result, and neither is a substitute for real game-playing evaluation.

### Recommended STAR Creator loop

**Inspect → Plan → Edit → Static-check → Run → Capture → Compare → Repair → Re-run → Verify**

Require separate gates for:
- code and type/lint checks;
- scene hierarchy and asset existence;
- runtime/play-session behavior;
- visual comparison against the acceptance criteria;
- performance and regression checks;
- rollback and artifact provenance.

Do not train on held-out benchmark tasks or copy benchmark ground-truth solutions into STAR's skill library.

## 3. New research: interaction-level alignment for full-duplex speech

**EMNLP 2026 paper:** https://aclanthology.org/2026.emnlp-main.2331/

*Multi-Faceted Interactivity Alignment in Full-Duplex Speech Models* argues that token-level language modeling alone does not directly optimize interaction behavior. It studies four axes:

1. pause handling;
2. turn-taking;
3. backchanneling;
4. user interruption.

The paper describes axis-specific reinforcement-learning rewards and an additional response-quality reward to guard against semantic degradation. It evaluates Moshi and PersonaPlex in offline and real-time multi-turn settings.

### STAR application

Do not start by fine-tuning a speech model on arbitrary stream recordings. First turn the four axes into a consented, reproducible evaluation suite around STAR's existing room director and call runtime.

| Axis | Positive behavior | Failure to measure |
|---|---|---|
| Pause handling | Distinguish hesitation from a completed thought | Premature cutoff |
| Turn-taking | Speak after the actual addressee finishes | Talking over a viewer |
| Backchanneling | Short acknowledgement when socially useful | Repeated filler or false acknowledgement |
| Interruption | Stop promptly when a person genuinely takes the floor | Treating every breath or noise as a barge-in |

Add semantic quality as an independent gate: a system that wins on response latency by producing irrelevant or empty replies has not improved.

For every candidate, report a Pareto frontier rather than one blended score:
- false cutoff rate;
- missed interruption rate;
- median and p95 response delay after true turn end;
- backchannel precision;
- addressee accuracy;
- semantic task success;
- user-overlap recovery time.

Use only properly licensed, consented audio. Keep benchmark audio evaluation-only unless its license and participant consent explicitly allow training. Speaker labels should remain session-scoped and must not become persistent voiceprints.

## 4. New research: Agent Memory Leaderboard Cycle 2

**Official platform:** https://agentmemoryleaderboard.ai/  
**Competition guide:** https://agentmemoryleaderboard.ai/

The official Cycle 2 guide describes separate Textual, Coding, and Multimodal memory tracks. Its task descriptions include cross-session and streaming memory, temporal events, memory governance, repository-context retrieval under noisy conditions, and image-linked evidence. The official page states that Cycle 2 results are expected on **2026-11-19**.

The guide also specifies important boundaries:
- participant-hosted Add/Search APIs are required for formal participation;
- Search returns memory evidence, not a generated final answer;
- samples, users, and tasks must remain isolated;
- source reuse and method changes must be disclosed;
- hard-coded answers, data leakage, and evaluation manipulation are prohibited.

The Cycle 2 material deadline has passed. This run does not submit STAR, deploy a public memory API, or send private STAR memories to the competition.

### STAR application: local memory quality suite

Adapt the dimensions locally without uploading user data:

- explicit fact recall;
- multi-hop/compositional retrieval;
- temporal updates and correction handling;
- coding/project experience retrieval;
- image-to-event association where consented;
- streaming memory write latency;
- stale-fact rejection;
- source/provenance preservation;
- deletion and retention policy compliance;
- cross-project and cross-user isolation.

A memory record should preserve source, timestamp, confidence, scope, and correction lineage. Summaries may accelerate retrieval but must not replace the evidence needed to audit or correct a claim.

## 5. Actual source-code improvement: invalidate stale partial ASR

### Repository observation

In `star/voice/call.py`, `CallSession._start_partial` runs a background ASR preview on a snapshot of the current audio. The worker correctly avoids taking the ASR lock if the final transcript is already using it. However, checking only whether the detector is non-idle is insufficient: the worker may finish after the original utterance has ended and a later utterance has started.

That can publish text from the old utterance into the new utterance's live caption stream.

### Implemented fix

A monotonically increasing `_partial_generation` token is now:
- advanced when a call starts or stops;
- advanced when a new speech turn starts;
- advanced when a turn ends or is discarded;
- captured by each asynchronous partial-transcript worker;
- checked again before the worker publishes a preview.

A worker whose generation no longer matches is silently discarded. Final transcription and canonical conversation history remain unchanged. Partial transcripts remain previews only.

### Regression test

`tests/test_voice_call.py` now uses a blocking fake ASR:
1. begin an utterance and hold its partial ASR result;
2. end that utterance;
3. begin a new utterance;
4. release the old ASR worker;
5. assert that the stale preview is never emitted.

This is a runtime correctness fix, not a claim of faster model inference. Exact-head CI must pass before calling it verified.

## 6. Streaming ASR: next engineering step, not yet implemented

The current voice interface is intentionally small: `SpeechToText.transcribe(pcm, sample_rate) -> str`. The Faster-Whisper implementation performs one-shot transcription. The partial preview path can therefore re-process an expanding audio snapshot.

Recommended next step:
- define an optional streaming-session protocol behind the existing ASR factory;
- preserve Faster-Whisper as a fallback and final-transcript path;
- use one session per utterance and feed each audio sample once;
- keep per-stream work single-threaded and all queues bounded;
- keep partial revisions in ephemeral UI state;
- only a finalized transcript may commit a turn, trigger tools, or enter durable memory;
- cancel the exact stream on barge-in, mute, device loss, timeout, and shutdown;
- release resource leases only after the host confirms stream closure.

Evaluate any NeMo-Speech.cpp prototype as an optional, pinned local backend. Review model and binary licenses separately; do not bundle weights or start an unpinned sidecar. Bind loopback-only by default and use the existing resource supervisor.

## 7. Intelligence and knowledge acquisition

STAR's general-knowledge pipeline should separate source acquisition from durable knowledge:

1. retrieve source material with date and provenance;
2. extract atomic claims rather than storing a whole page as one fact;
3. attach source, timestamp, scope, and confidence;
4. detect contradictions and newer corrections;
5. distinguish fact, inference, hypothesis, and preference;
6. verify high-impact claims against independent sources;
7. create a practice task or executable skill when the knowledge is procedural;
8. test transfer on an unseen task;
9. promote only after an external verifier passes;
10. preserve rollback and correction history.

This same pipeline can support science, history, programming, art, game mechanics, engineering, and practical troubleshooting. A large memory store is not the same as reliable knowledge.

## 8. Mixed-load acceptance: the stream is the product

Every candidate must be evaluated while the target machine is simultaneously:
- running the game;
- capturing and encoding OBS;
- animating the avatar;
- receiving audio and producing speech;
- handling chat/room events;
- performing a background research or creator task.

Record at least:
- time to first server token;
- time to first client chunk;
- time to first audible sample;
- p50/p95/p99 end-to-end response latency;
- ASR first-partial and final latency;
- false cutoff and interruption metrics;
- CPU, RAM, VRAM, GPU utilization and thermal/power state;
- game frame-time p50/p95/p99;
- audio underruns and output queue depth;
- OBS render skips and output drops;
- stale-action and cancellation rates;
- task success and skill-transfer scores.

Run a matched baseline and candidate with the same model, prompt, context, concurrency, game scene, stream settings, and task set. Report both quality and latency. Do not claim a speedup from a paper's different GPU or serving stack.

## 9. Integration sequence

### Now
- Land and verify the stale-partial-generation fix.
- Keep the existing room director, resource admission, task ledger, and delivery ledger authoritative.
- Add the multi-horizon game scorecard to local evaluations.

### Next
- Implement the streaming-ASR session adapter behind the existing engine factory.
- Add the four-axis interaction rehearsal suite.
- Add GameHorizon-inspired L1/L2/L3 task metadata to the game evaluation harness.
- Add evidence-linked memory tests for temporal corrections and coding/project retrieval.

### Then
- Connect authenticated OBS and VTube Studio adapters through the existing host supervisor.
- Connect a bounded real-time game-control adapter with action expiry and cancellation.
- Run Windows/RTX/audio/game/OBS hardware acceptance.
- Only then consider enabling any new default.

## 10. Capability-claim rules

Use these labels in docs, UI, release notes, and stream announcements:

- **Shipped:** included in a published release and covered by release notes.
- **Opt-in shipped:** included in a release but requires explicit setup and consent.
- **Draft implementation:** code exists on an unmerged branch or PR.
- **Research/evaluation only:** paper, benchmark, design, or offline harness.
- **Host acceptance pending:** requires actual Windows, GPU, microphone, game, OBS, or VTube Studio testing.

A successful GitHub Actions run is repository CI evidence, not proof of real-time streaming quality or physical hardware performance.

## References

- GameHorizon Suite project and benchmark: https://gamehorizon-suite.github.io/
- GameHorizon paper: https://arxiv.org/abs/2609.25001
- GameDevBench repository: https://github.com/waynchi/gamedevbench
- GameDevBench project page: https://sethkarten.ai/papers/gamedevbench.html
- OpenGameEval repository: https://github.com/Roblox/open-game-eval
- OpenGameEval paper: https://arxiv.org/abs/2610.02563
- Multi-Faceted Interactivity Alignment (EMNLP 2026): https://aclanthology.org/2026.emnlp-main.2331/
- Agent Memory Leaderboard: https://agentmemoryleaderboard.ai/
- NeMo-Speech.cpp: https://github.com/NVIDIA/NeMo-Speech.cpp
