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

The benchmark's key lesson is that false cutoffs and response delay move against each other. The correct target is a measured Pareto point for Star's own audience and languages, not the lowest possible delay.

Source: https://github.com/livekit/agents/tree/main/tests/benchmarks/eou

### Audio semantic turn detection

LiveKit's current audio Turn Detector has two variants: v1 is served through LiveKit Inference, while v1-mini runs locally on CPU. Unlike the older text turn detector, the audio detector does not depend on an STT transcript and can be used with realtime audio models. It still requires VAD; LiveKit requires VAD minimum-silence duration of at least 250 ms.

With the audio detector, LiveKit's default endpointing window is 300 ms minimum and 2.5 seconds maximum. If a prediction does not arrive within about one second, the session commits the turn rather than waiting indefinitely. The detector supports 14 languages. The local v1-mini weights use about 140–250 MB per loaded copy, depending on process/runtime.

This is a strong experiment for Star: CPU-only semantic turn detection can leave the GPU available for the main language model, game rendering and avatar work. It is not a guaranteed speedup; measure CPU load, memory, endpointing latency and game/OBS stability on the target machines.

Important distinction: LiveKit's older text turn detector uses STT transcripts and is deprecated for new agents. Its 396 MB / ~50–160 ms per-turn benchmark belongs to that text model, not the current audio v1-mini. Do not conflate the two.

Sources:
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://github.com/livekit/agents/tree/main/tests/benchmarks/eou

### Two-loop streaming architecture

Keep a fast live perception/turn-taking loop separate from slower research, game strategy and tool execution. The semantic turn detector only contributes an endpointing signal; it must not block owner barge-in, override guest-speech holds or wait for background reasoning. When using LiveKit's detector with a realtime model, disable the model's built-in turn detector so two endpointing systems do not conflict.

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
6. If the semantic detector says the speaker is continuing, keep STAR silent until the maximum endpointing budget. If a prediction is missing/stale or still says continue at 2.5 seconds, a fresh VAD-silence decision may use the bounded timeout fallback; owner, guest and stale-VAD holds still take precedence.

The semantic gate can delay or permit a response. It cannot authenticate the owner, override guest speech, authorize a tool action or trigger an actual audio interruption. The host still owns playback stop, stage interruption and avatar cancellation.

### Default engineering bounds

| Setting | Default |
|---|---:|
| Prediction freshness | 500 ms |
| Maximum audio-end-to-decision budget | 2,500 ms |
| Timeout fallback | After 2,500 ms, only with fresh VAD silence and a host-supplied audio-end timestamp |
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
- Model speed: the local audio v1-mini runs on CPU and uses roughly 140–250 MB per loaded copy; it is a candidate to reduce GPU contention, but CPU contention and actual latency must be measured on Star's machines.
- Evaluation: LongMemEval-V2 is relevant to remembering evolving game/project state and workflow gotchas; SIMA 2 motivates held-out multiworld skill-transfer tests and self-directed practice.

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
3. LiveKit, [Audio Turn Detector defaults and local fallback](https://docs.livekit.io/agents/logic/turns/turn-detector/) — VAD minimum silence, 14 languages, v1-mini CPU use and the 2.5-second maximum endpointing behavior.
4. NVIDIA, [AIPerf metrics](https://docs.nvidia.com/aiperf/metrics.html) — TTFT, inter-token latency, request latency and throughput measurement.
5. Wu et al., [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) — agentic memory across evolving multimodal trajectories.
6. Google DeepMind, [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) — multiworld instruction following, held-out game generalization and self-directed skill improvement.
