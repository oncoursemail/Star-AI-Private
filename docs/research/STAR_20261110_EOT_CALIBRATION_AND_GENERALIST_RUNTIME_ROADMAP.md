# STAR — End-of-Turn Calibration, Real-Time Intelligence and Generalist Runtime Research

**Research date:** 2026-11-10  
**Implementation:** offline, per-language end-of-turn operating-point calibration with a conversation-separated holdout gate.  
**Runtime effect:** none; this change never downloads a model, changes a live threshold, or captures audio.

## Executive summary

STAR now has separate development foundations for trusted VAD/owner arbitration, an optional semantic end-of-turn adapter, multi-party voice evaluation, a cross-modal event timeline, game live-clock evaluation, inference metrics and model-quality gating. The missing piece in the semantic turn path is a reproducible way to select and validate its per-language operating point.

A single global threshold or a claim that a detector is "more human" is not enough. End-of-turn systems trade off two different failures:

1. False cutoff: STAR starts speaking while a person is only pausing mid-thought.
2. Conversational dead air: STAR waits too long after the person has genuinely finished.

This update adds a calibration harness that replays the first threshold crossing across timestamped score observations, sweeps thresholds on a calibration split, and evaluates the selected threshold on an untouched conversation-level holdout split. It reports one-sided Wilson upper confidence bounds over independent conversation groups for both false cutoffs and missed turns. A threshold is only marked for manual review when both splits have sufficient samples and the holdout meets the configured constraints.

## 1. Research findings applied

### LiveKit audio turn detection

LiveKit's current audio Turn Detector uses acoustic and semantic signals rather than requiring an STT transcript. The documentation distinguishes the hosted v1 model from local CPU v1-mini, requires VAD, sets a minimum VAD silence duration of 250 ms, and documents 14 supported languages. Its audio detector uses 300 ms minimum and 2.5 s maximum endpointing defaults; language-specific thresholds can be supplied. When no STT language is configured, the detector defaults to English thresholds.

The important engineering implication is not to copy a default threshold blindly. The host should evaluate each language and runtime/model combination separately, and should measure CPU load as well as conversational quality. A local CPU detector may preserve GPU capacity for the language model, rendering and avatar, but it can still contend with the game or other CPU work.

Source:
- https://docs.livekit.io/agents/logic/turns/turn-detector/

### LiveKit EOT benchmark

The open livekit/eot-bench project evaluates the latency-versus-false-cutoff tradeoff using pause opportunities in 14 languages. It sweeps policy thresholds and reports Pareto operating points rather than treating one accuracy number as sufficient. Its README explicitly distinguishes conversational endpointing delay from model inference time: a detector can compute instantly and still leave dead air if its policy waits too long.

The new STAR harness adopts this two-axis evaluation and adds an independent holdout requirement before a threshold can be recommended. It replays the first time a score crosses each threshold, so a more conservative threshold can produce a later decision timestamp rather than reusing one fixed decision time. The public dataset is not copied into STAR; adapters can export metadata-only score timelines from a separately licensed/approved local evaluation run.

Sources:
- https://github.com/livekit/eot-bench
- https://github.com/livekit/eot-bench-data

### NVIDIA AIPerf

NVIDIA AIPerf distinguishes time to first token (TTFT), time to second token, inter-token latency (ITL), request latency and throughput. TTFT includes network/queueing, prompt processing and first-token delivery; it is not pure model-kernel time. STAR should keep these inference metrics separate from end-of-speech-to-first-audible-PCM and from endpointing policy delay.

Source:
- https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference

## 2. Implementation added

New module: star/voice/eot_calibration.py

The module is standard-library-only and defines:
- ScoreObservation: a host-monotonic timestamp and end-of-turn probability.
- EOTTrial: metadata-only labeled final-turn or mid-turn pause, model ID, language, conversation group, split and a bounded sequence of score observations.
- CalibrationConfig: threshold grid, false-cutoff budget, missed-turn budget, maximum response delay, confidence level and minimum sample counts.
- evaluate_threshold: replays the first score crossing for a threshold and reports false-cutoff rate, missed-turn rate, median and p95 response delay, plus one-sided Wilson upper confidence bounds.
- calibrate_end_of_turn: sweeps only the calibration split, selects the feasible threshold with the lowest p95 response delay, and requires the untouched conversation-level holdout split to pass before returning manual_review_recommended.
- A JSONL CLI with duplicate-key rejection, strict field allowlists, input/record/observation bounds, aggregate-only output and overwrite protection.

The report omits example IDs, conversation-group digests, raw media, transcripts, speaker IDs and chat. Input validation rejects unknown fields, so accidental transcript/media fields cannot be silently ingested. Duplicate examples and conversation groups crossing the calibration/holdout boundary are rejected. The output explicitly says that no automatic runtime change was made.

### Trial semantics

For a true end-of-turn example, reference_ms is the independently annotated end-of-speech timestamp. The response delay is the timestamp of the first threshold crossing minus that reference.

For a mid-turn pause, reference_ms is pause start and resume_ms is when the speaker resumes. A false cutoff occurs only when the first threshold crossing occurs before the speaker resumes. A crossing after the speaker resumes is not counted as an interruption.

Each trial contains the detector's time series of end probabilities. This matters: threshold sweeps must replay the first crossing at each threshold; they must not reuse one fixed decision timestamp for every threshold. All timestamps must already be mapped by the trusted host to the same monotonic clock. This module does not attempt to synchronize clocks or infer labels.

### Selection policy

A model/language cohort is considered separately. Conversation groups must be assigned to exactly one split before any threshold selection. The host should use a random opaque identifier or keyed HMAC that is stable within one evaluation run; it should not use a plain hash of names, transcripts or other low-entropy personal data. The calibration split must meet minimum positive and negative conversation-group counts. Event-level rates are reported, but the confidence bounds used for gating are conservative conversation-level failure bounds: a conversation is counted as failed if any of its labeled opportunities has a false cutoff or missed turn. This avoids treating many pauses from one long conversation as independent samples. For each threshold, the harness calculates one-sided Wilson upper confidence bounds for these conversation-level failure rates. It chooses the feasible threshold with the lowest p95 response delay, with median delay and then higher threshold as deterministic tie-breakers. The same threshold is then evaluated on the untouched holdout split. If either split is too small, or no operating point meets the constraints, the result is inconclusive rather than a guessed recommendation.

The default minimum of 100 positive and 100 negative conversation groups per split is deliberately conservative. For small private rehearsals, lower sample counts can be used for exploratory diagnostics, but such results should not be treated as release evidence.

## 3. Wider Star architecture recommendations

### Natural VTuber interaction

Keep the live loop separate from background reasoning. The live loop should handle VAD, semantic endpointing, addressee/floor awareness, barge-in, short responses and avatar timing. Background workers can research viewer questions, retrieve memories, analyze a game strategy or plan a game-development task. A slow research job must never block a live acknowledgement or urgent game reaction.

Evaluate separately:
- false cutoffs during mid-sentence pauses;
- missed turns;
- end-of-speech to first audible PCM;
- owner barge-in reaction time;
- interruptions while another person is speaking;
- continuation through backchannels and background speech;
- per-language performance;
- CPU/RAM use and game/OBS frame-time impact.

Naturalness means appropriate timing, listening, restraint, continuity and expressive delivery. STAR should remain transparent that she is an AI streamer rather than impersonating a human.

### Generalist game learning

Google DeepMind's SIMA 2 research describes a language-conditioned agent that reasons about goals, interacts with multiple 3D environments and learns over time. The practical lesson for STAR is to evaluate transfer across held-out environments rather than only score memorized action sequences.

The October 2026 Gym-Anything-RT preprint focuses on real-time visual interaction, where the world changes while the model thinks. STAR's game evaluation should therefore preserve a live clock and separately report paused-environment performance, reaction latency, action success, objective completion, deaths/failures and skill transfer.

Recommended game loop:
1. Observe the current screen and permitted game state.
2. Infer the objective and uncertainty.
3. Choose a bounded action or ask for clarification.
4. Execute through an approved input adapter.
5. Observe the result on the next frame.
6. Compare predicted and actual outcomes.
7. Update a versioned skill only after repeatable held-out success.

Sources:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- https://arxiv.org/abs/2610.37567

### Game creation and Roblox Studio

Use an inspect-before-edit pipeline: read project structure and relevant objects, make a small change in an isolated test experience, run Luau/static checks, launch a playtest, inspect visual output, test gameplay, repair and repeat. Keep publish, live data-store, monetization, network and player-impacting operations behind explicit owner approval. The new Roblox Studio MCP/Open Cloud permission work remains opt-in and should not be broadened automatically.

### General knowledge and memory

LongMemEval identifies information extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention as distinct long-term memory capabilities. STAR should preserve provenance and timestamps, distinguish observed facts from inference, retrieve the latest valid fact when knowledge changes, and abstain when evidence is missing. Memory should be tested on held-out multi-session questions rather than only replaying the same development prompts.

Sources:
- https://xiaowu0162.github.io/publications/13_longmemeval/
- https://github.com/xiaowu0162/LongMemEval

### Faster inference without quality loss

Keep separate measurements for:
- endpointing policy delay;
- detector compute latency;
- client-observed TTFT;
- TTST/ITL and output throughput;
- end-to-end response completion;
- first audible PCM;
- queue wait and deferred requests;
- game frame-time and OBS/audio health.

Compare model/runtime candidates on paired prompts and identical output limits. Run the same tests with the game, OBS, voice, avatar and background workers active. A model should not be promoted solely because it has higher tokens/sec if it worsens answer quality, first audible response, p95 latency or live game stability.

## 4. Acceptance plan

1. Export metadata-only score timelines from VAD-only, local semantic detector and any hosted detector.
2. Split by conversation/session before threshold selection; never split adjacent pauses from the same conversation across calibration and holdout.
3. Run per-language calibration and holdout evaluation.
4. Compare against the VAD-only baseline at the same false-cutoff budget.
5. Run a 30–60 minute private stream rehearsal with a game, OBS, TTS, avatar, owner voice and at least one guest.
6. Record median/p95/p99 latency, false cutoffs, missed turns, game frame-time, OBS drops, audio underruns, CPU, RAM, GPU and VRAM.
7. Require manual review before any live threshold change; keep the existing trusted VAD/owner gate authoritative.

## 5. Limitations

- This is an offline calibration and reporting tool, not a detector or audio integration.
- It does not download or install LiveKit, model weights or a new runtime dependency.
- It does not alter SemanticTurnGate defaults or the live streaming path.
- Threshold quality depends on valid independent annotations, complete score timelines, clock mapping and a genuinely untouched conversation-level holdout split.
- No real-stream naturalness improvement, latency reduction, gameplay mastery, model intelligence gain or hardware speedup is claimed until measured on STAR's target machines.
