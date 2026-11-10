# STAR — Semantic End-of-Turn and Natural VTuber Conversation Research

**Research date:** 2026-11-10  
**Implementation:** optional semantic end-of-turn gate layered over the existing trusted VAD/owner gate.  
**Scope:** content-free adapter for host-provided predictions; no LiveKit dependency, audio capture or model download is bundled.

## Executive finding

Natural conversation is not just speech-to-text plus a fixed silence timer. A listener must distinguish a completed turn from a mid-sentence pause, a backchannel, a laugh, a second speaker, an interruption and an utterance directed at someone else.

The existing STAR TurnTakingGate already has valuable hard guarantees: trusted owner identity comes only from the host-authenticated source; guest voice and uncertain VAD hold speech; playback echo must be cleared; and actual barge-in still requires the host to stop playback and interrupt the stage. Its limitation is that it is primarily a VAD/silence advisor. A semantic end-of-turn model can improve the decision about whether the speaker has actually finished.

## 1. Research findings

### LiveKit end-of-turn benchmark

LiveKit's EOT benchmark contains real pause segments across 14 languages, including pauses of at least 100 ms. It evaluates the tradeoff between response latency and false cutoffs rather than treating one threshold as universally correct.

The published benchmark shows that the Turn Detector v1's false-cutoff rate changes materially as the latency budget changes (for example, approximately 9.9% at a 300 ms budget and 4.5% at 600 ms in the reported setup). The correct target is a measured Pareto point for Star's own audience and languages, not the lowest possible delay.

Source: https://github.com/livekit/agents/tree/main/tests/benchmarks/eou

### Local CPU turn detection

LiveKit documents a local Turn Detector v1-mini option. Its published guidance describes roughly 396 MB of model weights and about 50–160 ms inference per turn on a typical CPU, with no hosted inference cost. Actual performance depends on CPU, language, audio length and runtime.

This is an attractive experiment for Star because a small CPU turn detector may leave the GPU available for the main language model, game rendering and avatar work. It is not a guaranteed speedup: measure it on the target Brain 1/Brain 2 hardware under simultaneous game, OBS and TTS load.

Sources:
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://huggingface.co/livekit/turn-detector

### Full-duplex architecture

Realtime-Venus research separates a fast perception/conversation loop from a slower reasoning/delegation loop. The useful lesson is to keep live turn decisions responsive while background research, game strategy or tool execution proceeds independently. Star should not wait for a long research task before acknowledging an audible owner interruption.

Source: https://arxiv.org/abs/2609.11842

## 2. Implementation added

New module: star/stream_semantic_turn.py

The module defines:
- SemanticTurnPrediction: a bounded, content-free receipt containing a host turn ID, sequence, audio-end timestamp, decision timestamp, completion flag, detector name, language, optional confidence and optional detector latency.
- SemanticTurnGate: wraps the existing TurnTakingGate and returns the existing TurnAdvice type.

The adapter has no dependency on LiveKit and does not receive PCM, transcripts, speaker names or chat text. A Windows host can later translate a LiveKit or other semantic endpointing result into the receipt.

### Decision order

1. Run the existing trusted VAD/owner gate first.
2. If authenticated owner barge-in is confirmed, return owner-yield immediately; semantic prediction cannot delay it.
3. If VAD is stale, echo is uncleared, guest speech is active or another existing hold applies, preserve that hold.
4. Only when the VAD gate says trusted silence may semantic endpointing permit speech.
5. Require the prediction to match the exact current turn ID, arrive within its freshness and endpointing budgets, use a monotonically increasing sequence, and pass the configured confidence threshold when confidence is available.
6. If the semantic detector says the speaker is continuing, keep STAR silent.

The semantic gate can delay or permit a response. It cannot authenticate the owner, override guest speech, authorize a tool action or trigger an actual audio interruption. The host still owns playback stop, stage interruption and avatar cancellation.

### Default engineering bounds

| Setting | Default |
|---|---:|
| Prediction freshness | 500 ms |
| Maximum audio-end-to-decision budget | 2,500 ms |
| Minimum confidence when supplied | 0.50 |
| Recent turn sequence history | 32 turn IDs |
| Accepted detector identifiers | LiveKit v1, LiveKit v1-mini, custom |
| Stored media/transcript | None |

These are conservative starting limits. Tune them only against measured false-cutoff and latency results.

## 3. Why this makes VTuber conversation more natural

A fixed silence threshold can cut off a speaker who pauses to think, while a very long threshold makes STAR feel slow. Semantic endpointing can recognize when an utterance is complete even if the pause is short, and can continue holding through a hesitation that sounds like silence.

The desired behavior is:
- do not interrupt viewers during mid-sentence pauses;
- do not answer a backchannel as though it were a completed question;
- distinguish viewer speech from authenticated owner barge-in;
- remain silent when another person is being addressed;
- resume only after both trusted VAD and semantic turn completion agree;
- preserve a natural delay/false-cutoff tradeoff for each supported language.

Silence is a valid action. A more human-feeling streamer does not need to react to every sound.

## 4. Performance evaluation plan

Compare three endpointing configurations with the same audio sessions:
1. Existing VAD-only gate.
2. VAD plus LiveKit Turn Detector v1-mini on CPU.
3. VAD plus full Turn Detector v1, if the hardware budget permits.

Record:
- end-of-speech to first audible PCM;
- false-cutoff rate;
- missed-turn rate;
- interruptions during mid-sentence pauses;
- owner barge-in reaction time;
- CPU utilization and peak memory;
- GPU/VRAM contention with the main model;
- game frame-time and OBS dropped-frame changes.

Report median, p95 and p99, not only averages. Keep per-language results separate. Do not compare different prompts, audio codecs or game loads as though they were paired trials.

## 5. Relationship to Star's wider intelligence

- Game-playing: semantic endpointing lets STAR listen to a viewer while the game loop continues; it must not block reflex actions or gameplay observation.
- General knowledge: long research questions can be delegated to the background brain after the live brain acknowledges the viewer.
- Memory: store the fact that a turn occurred and what STAR actually said, not raw microphone audio by default. Preserve the distinction between speech recognized, speech actually played and speech interrupted.
- Model speed: a small CPU endpointing model is a candidate to reduce GPU contention, but its 50–160 ms published typical-CPU estimate must be remeasured on Star's machines.
- Evaluation: LongMemEval-V2 is relevant to remembering evolving game/project state and workflow gotchas; SIMA 2 and Gym-Anything-RT motivate evaluating gameplay under a live clock rather than paused screenshots.

## 6. Acceptance tests

The new tests cover:
- semantic completion after trusted VAD silence;
- a mid-turn pause remaining held;
- missing, stale, future and overlong predictions;
- exact turn-ID matching;
- monotonically increasing prediction sequences and replay rejection;
- low-confidence decisions;
- authenticated owner yield taking precedence;
- guest voice holding even when the semantic model says complete;
- no raw audio, transcript or turn ID in metrics.

Before enabling a LiveKit adapter in the desktop app, run a private 30–60 minute rehearsal with actual microphone capture, speaker playback, OBS, VTube Studio, a live game and viewer chat. The adapter is opt-in and no model is downloaded by this change.

## Sources

1. LiveKit, [End-of-turn benchmark](https://github.com/livekit/agents/tree/main/tests/benchmarks/eou) — 14-language pause benchmark and latency/false-cutoff tradeoff.
2. LiveKit, [Turn Detector documentation](https://docs.livekit.io/agents/logic/turns/turn-detector/) — local and hosted semantic endpointing options.
3. LiveKit, [Turn Detector model card](https://huggingface.co/livekit/turn-detector) — v1 and v1-mini model details.
4. NVIDIA, [AIPerf metrics](https://docs.nvidia.com/aiperf/metrics.html) — TTFT, inter-token latency, request latency and throughput measurement.
5. Wu et al., [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) — agentic memory across evolving multimodal trajectories.
6. Google DeepMind, [SIMA 2](https://deepmind.google/discover/blog/sima-2-a-generalist-ai-agent-for-3d-virtual-worlds) — multiworld instruction following and game-agent learning.
7. Gym-Anything-RT, [real-time game-agent benchmark](https://arxiv.org/abs/2610.22003) — why paused-environment performance is not live gameplay mastery.
