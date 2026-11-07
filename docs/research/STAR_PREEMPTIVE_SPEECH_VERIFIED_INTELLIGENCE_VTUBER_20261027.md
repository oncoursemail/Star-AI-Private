# STAR AI — Verified Preemptive Speech, Gaming Intelligence and Natural VTuber Roadmap

**Technical research, October 27, 2026.** This document distinguishes implemented, offline-tested control-plane behavior from proposed streaming and intelligence improvements. STAR Core Forge remains the local-first source of truth; GitHub is an optional draft-review mirror.

## The new concrete improvement: faster possible conversation without premature speech

A natural gaming VTuber must listen until a human finishes speaking, then respond with minimal awkward delay. LiveKit's 2026 turn-handling system documents **preemptive LLM generation** that overlaps computation with turn completion, while leaving TTS disabled until the final user turn is confirmed. It also warns that speculative responses can become invalid after transcription changes. Sources:

- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/reference/agents/turn-handling-options/

STAR previously had an evidence-grounded director, StagePlan, hardware-aware QoS, interruption coordinator, and playback acknowledgements, but not a verified way to reuse a draft LLM answer after a provisional voice transcript changed. This branch introduces a bounded, **opt-in control plane**, not an automatic voice agent.

### Implemented

**star/stream_preemptive_host.py** introduces StreamPreemptiveHost, which performs all of the following:

1. An authenticated local host pre-moderates provisional STT text and builds the complete intended LLM input, including fixed persona, permitted facts, game state, and source scope. The host fingerprints this full prompt and tags the transcript revision.
2. Preemptive computation must first obtain a real **commentary inference lease** through the existing StreamBrainGovernor, which enforces trusted telemetry, game performance backpressure, worker reservations, and real execution deadlines. No admission means no speculation.
3. STAR's host can execute one **LLM-only** preview. No audio, TTS, avatar action, OBS broadcast, or tool execution is initiated by this component.
4. The host confirms the final moderated transcript. Whitespace-only normalization is allowed. Any changed punctuation, words, transcript revision, or full prompt digest **invalidates** the draft. Same game/event identity and live governor generation are required.
5. Independently moderated output is eligible only after the local application attests the model worker has physically stopped. Canceling or timing out a worker never fabricates freed CPU/VRAM. An unacknowledged worker blocks replacements.
6. A prepared StagePlan for the **same signal ID** is required to claim the answer exactly once. STAR checks the exact active plan object, intended event type, stage deadline, session generation, and prompt digest before returning the candidate.
7. Claiming a response is not speaking. The trusted host must separately request a speech QoS lease, start the local TTS pipeline, enforce actual audio-device acknowledgement, and handle owner interruptions with physical stop and avatar queue flush.

Two small compatibility additions make this enforceable: StarStage.prepared(plan) verifies current-plan identity, while StreamBrainGovernor.prepared_plan(plan) and session_generation() verify that the prepared plan belongs to the running session.

**What does NOT change:** model weights, system permissions, playback devices, voice synthesis, OBS settings, underlying neural reasoning speed, game input permissions, or automatic public content. No microphones, chats, model output or prompts are persisted in logs/metrics. The response text is held briefly in RAM until consumed or discarded. The gate must only be invoked by the trusted embedding app, never by a viewer or an LLM tool.

**Important cold-start behavior:** current QoS rejects uncalibrated live commentary paths, including speculative previews. The host must collect real, same-game-load latency evidence first. This protects STAR's RTX 4060 gaming priority. A rejected preview is harmless silence; it must never trigger a GPU fallback under FPS pressure.

### Synthetic integration coverage

The offline tests cover exact-match final transcripts, early finalization before model completion, mismatched punctuation, changed words, unexpected extra speech, changed game/public context, transcription revision drift, no speaker/moderation attestation, old session reuse, expired deadlines, revoked jobs retaining their reservations, stale StagePlan copies, single-use claims under parallel contention, and unmeasured live-route refusal. They do not claim a real latency improvement.

## Research 1 — more intelligence per unit of compute

Divide STAR into four latency classes rather than running an expensive language model on every situation.

| Cognitive loop | Suitable work | Evidence required |
| --- | --- | --- |
| Reflex (milliseconds) | Fixed/compact verified game cues, immediate danger, input deadlines | Trusted observations and allowed action rules |
| Conversation (subsecond target, not measured) | Moderated live questions, brief grounded replies, interruptible audio | Final STT, fresh plan, first audible PCM, correctness |
| Strategist (seconds) | Unfamiliar mechanics, level navigation, debugging, construction planning | Scene inspection, predicted result, instrumented playtest |
| Night school (offstream) | Best-of-N builds, self-generated challenges, retrieval, harder evaluations | Independent game-engine tests, held-out tasks, versioned lessons |

For the owned RTX 4060 8 GB and planned 32 GB RAM system: prioritize game rendering, use CPU speech when frame-time telemetry degrades, and benchmark cheap/fallback model routes. First compare quantization, prompt caching, llama.cpp speculative decoding, short stable system prefixes, KV reuse, chunked prefill, and RAM offload **one variable at a time**. Realistic mixed prompts and cache-integrity canaries are essential; unrepresentative repeated prompts exaggerate gains.

The official llama.cpp SPEED-Bench provides per-category latency, throughput, and draft-token acceptance measurements for speculative decoding. A draft model is not automatically faster on STAR's hardware:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## Research 2 — learning to actually play games well

Roblox's **October 1, 2026 OpenGameEval** runs stateful executable Roblox Studio checks across 84 tasks and reports that inspecting relevant objects before editing correlates with higher completion rates. The **October 19, 2026 CEGame-Bench** studies long-horizon game creation in five engines and reports that only 16% of tested agent runs reach the game ending.

- https://arxiv.org/abs/2610.02563
- https://arxiv.org/abs/2610.26098
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://create.roblox.com/docs/studio/mcp

STAR should progress beyond executing a script or displaying a good screenshot. A stronger learning cycle is: inspect controls and scene -> predict a consequence -> execute an authorized private test action -> observe objective and visual state -> diagnose cause of failure -> correct -> independently verify -> save a versioned reusable lesson. Collect signed practice feedback only; never train from a chat viewer claiming STAR won.

Test **transfer**, not memorization: unfamiliar obby layouts, racing tracks, object interactions, new physics conditions, and controlled shooter mechanics. Use holdout levels and game versions that the training loop cannot read. Evaluate action timing, completion rate, prediction calibration, sample efficiency, adverse frame-rate impact, and whether the skill persists after resets. A multi-game fair curriculum should keep practice from collapsing into a single game.

For game building, require end-to-end playable objectives, no floating/misplaced props, correct joins, collision volume checks, functional UI safe areas, coherent VFX and animation, proper materials and UVs, save/reload integrity, and camera-angle inspections. Roblox's built-in Studio MCP/Playtest Agent should be used for authorized development and private playtesting, not as an uncontrolled public-game input channel.

## Research 3 — general knowledge that is actually trustworthy

Use a versioned, provenance-aware knowledge pipeline rather than indiscriminately collecting internet text. Separate approved public documentation, game/engine manuals, reviewed personal notes, owner-private information, and observed game experiences. Every reusable claim should include a source/version/date, rights to store/use it, expiry or recheck rule, and a validation signal. Privately held memories do not automatically become on-air public facts.

Quality must be tested with fact questions STAR can answer, adversarial unsupported questions she should abstain from, Roblox/Luau API changes, code execution outcomes, UI aesthetic review, and knowledge freshness. Prefer retrieval from authoritative docs plus verified local worked examples; avoid treating generated text as self-confirming evidence.

## Research 4 — very natural humanlike streaming

**Being an expressive AI character** is achievable without falsely claiming to be biologically human or fabricating childhood memories. STAR can establish a persistent character identity through real digital episodes: games she actually completed, live interactions viewers opted into, drawings she made, construction mistakes she fixed, recurring jokes, and independently verified accomplishments.

The streaming stack should combine turn-aware silence and interruption recovery with synchronized facial movement, expressive eye motion, hair physics, game-contingent relief and laughter, and stable cat/puppy modes. Not every event deserves speech. The exact spoken audio PCM, not an unverified text guess, should drive mouth and motion cues. False interruptions should not erase a sentence permanently, and owner interruption should stop speech physically before avatar neutral reset.

Kyutai's October 2026 Pocket TTS small English models (18.2M, 6.9M, 1.9M parameters) are **candidate CPU speech routes**, not measured STAR performance. Evaluate pronunciation, latency, expressiveness, game FPS, VRAM and voice consistency together:
https://github.com/kyutai-labs/pocket-tts

LiveKit's turn detection and endpointing approaches are useful for reducing awkward delays, while measuring false interruptions and respecting downstream speech consent:
https://docs.livekit.io/agents/logic/turns/turn-detector/

## Real Windows A/B acceptance plan

A meaningful trial must run against **STAR's actual dedicated Windows gaming machine**, real game frame-present telemetry, microphone/STT input, model route, local speaker playback, avatar controller, and opt-in OBS rehearsal.

**Baseline A:** wait for final transcript, then run LLM and TTS.

**Candidate B:** permit exactly one telemetry-admitted preview LLM; **never** generate or play TTS preemptively; reuse only if final transcript, prompt and exact prepared StagePlan match.

Use at least 20 randomized paired, *different* moderated questions in each game scenario, with the same models, prompts, time of day and game version. Record anonymous aggregates: preempt-reuse rate, cancelled/wasted token cost, p50/p95 final-turn-to-first-audible time, incorrect/premature audio count, 1%-low FPS, p99 frame time, VRAM and CPU peaks, response correctness, game-input responsiveness, and interruption recoveries. Deliberately test scene switches, transcript corrections, extra final words, cancellations that race with model finish, missing telemetry, two speakers, outdated public facts, and no current StagePlan.

**Release criteria:** zero prematurely audible utterances; no unverified knowledge or game wins; improved paired p95 conversational responsiveness on most turns; no meaningful game FPS/VRAM or answer-quality regression; a one-click rollback; clear owner consent. No speed win is claimed until these real trials pass. A synthetic integration test proves only that a control-plane policy behaved as specified.

## Prioritized next increments

1. Wire the new host into real STT finalization, independent moderation, actual commentary worker stop acknowledgements, and the existing stage/QoS/CPU TTS pipeline on the authorized Windows machine.
2. Add independent geometry/gameplay-completion evaluations with multi-camera checks and automated save/reload, not only Luau lint or generated screenshot scoring.
3. Benchmark adaptive gameplay models plus lightweight CPU TTS in the same game, with paired TTFA and FPS measurements before auto-selection.
4. Expand source-verified cross-domain knowledge and held-out difficult challenges; publish only approved, supported and genuinely improved skill lessons.
5. Build real episodic memories and expressive rig/audio timing from opt-in, verified events—not invented personal history or generic canned streaming scripts.

**Security and ownership:** Keep all new features opt-in. Streaming, public posting, irrevocable outside actions and spending require their appropriate owner-defined authorization gates. GitHub is a draft review mirror; Star Core Forge should own local diffs, independent tests, rollback, and experiment histories. Note separately that the GitHub repository named Star-AI-Private currently appears publicly visible, so secret/private streams and credentials must never be committed there.
