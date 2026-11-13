# STAR streaming ASR, diarization, and learning-system decision research

**Research date:** 2026-11-13  
**Repository context:** `oncoursemail/Star-AI-Project`, desktop voice and opt-in `RoomStreamHost` work.  
**Decision type:** research-backed integration plan; no speech model is installed or enabled by this document.

## Executive decisions

1. **Keep turn detection separate from transcription.** Low-latency VAD / interruption detection must remain responsive even when ASR emits text only at chunk boundaries. A recognizer's chunk cadence is not a safe barge-in clock.
2. **Benchmark Microsoft's VibeVoice-ASR-Streaming 1.5B and 7B as speaker-attributed ASR candidates.** It emits transcript text per audio chunk and combines recognition with speaker attribution, avoiding a mandatory second diarization pass. The official checkpoint configuration supplies its chunk and look-ahead geometry; STAR must read those values instead of hard-coding them.
3. **Benchmark VibeASR.cpp BitNet separately as a CPU-first option.** It is a different, quantized VibeVoice-ASR model/runtime—not the same streaming checkpoint. Its published i7-13700 / Windows 11 results are promising for freeing GPU memory, but they are not a prediction for STAR's actual CPU.
4. **Keep Nemotron 3 Diarization as a modular alternative / comparison.** It supports up to eight speakers in the reported streaming Sortformer configuration. Compare modular ASR+diarization against unified speaker-attributed ASR on the same recordings.
5. **Do not connect raw partial hypotheses directly to RoomStreamHost.** Partial chunks may be revised, incomplete, or end mid-sentence. Keep them in a bounded, session-local caption/hypothesis channel. Only a finalized, policy-classified utterance may become a `RoomCue` and enter the existing queue/payload path.
6. **Treat human-feeling streaming as an evaluation problem.** Measure whether STAR speaks at the right time, responds to the right person, handles overlap, and remains grounded over long sessions—not just voice quality or ASR word error rate.

## Research findings

### 1. VibeVoice-ASR-Streaming

Microsoft's September 2026 technical report describes a speaker-attributed streaming ASR model that interleaves fixed audio chunks, a small look-ahead, and prior text. The report releases 1.5B and 7B checkpoints; the 7B model reports the strongest average WER/CER across five evaluation sets and best or tied-best speaker attribution in 12 of 13 settings.

The official repository's streaming guide states that the model emits text once per audio chunk and reads the trained chunk/look-ahead values from `preprocessor_config.json`. Its reference inference loop returns one `chunk_text` per chunk and concatenates the chunk texts for the final transcript.

**Implications for STAR:**

- Create a backend-neutral streaming-ASR adapter interface, not a hard dependency on VibeVoice.
- At adapter startup, inspect model metadata and expose sample rate, chunk duration, look-ahead, supported languages, speaker-attribution support, device, and model revision.
- Maintain one streaming state / KV cache per live audio session; do not reload the model or re-prefill the entire history for every chunk.
- Preserve chunk sequence and audio-time boundaries. A reconnect or model restart begins a new stream epoch; never append chunks across epochs.
- Treat speaker labels as ephemeral session-local labels. Do not map them to persistent viewer identities or voiceprints.
- Use the model's own chunk geometry. One third-party MLX implementation reports a 2.933-second new-audio window plus 0.533-second look-ahead for its compatible checkpoint; that is implementation/checkpoint-specific, not a constant to copy into STAR.
- Keep partial captions separate from final conversational events. A live caption can update while the speaker is still talking; the Social Director should wait for end-of-turn finalization unless an independently validated emergency/game cue justifies interruption.

**Hardware caution:** the official streaming guide recommends a CUDA/PyTorch environment and FFmpeg. A 1.5B streaming model may compete with STAR's local LLM, game, and OBS for the same 8 GB GPU. Do not enable it by default on the gaming GPU. First benchmark it on a secondary worker or in a reserved-memory rehearsal.

### 2. VibeASR.cpp / VibeVoice-ASR-BitNet

Microsoft's separate CPU runtime uses heterogeneous quantization (I8_S VAE + I2_S language model). Its README reports a reduction from 4.62 GB to 1.58 GB and 1.6–2.7× faster inference than Whisper.cpp in its tested comparisons. It reports an Intel Core i7-13700 / Windows 11 / MinGW GCC real-time factor of 0.93 with one thread, 0.56 with two, and 0.43 with three. The same table reports an absolute WER increase of roughly 1–4 percentage points against the larger VibeVoice-ASR reference on the listed evaluation sets.

**Important distinction:** these results describe the BitNet CPU runtime for VibeVoice-ASR, not the 1.5B/7B VibeVoice-ASR-Streaming checkpoints. Do not describe BitNet as the streaming model.

**STAR decision:** this is the first CPU-first candidate to benchmark on the actual STAR host. Start with a 2-thread cap, then compare 3 threads. Record real-time factor, model warm-up, CPU utilization, game frame-time p95/p99, audio underruns, and transcript quality. If it cannot sustain RTF < 1 with headroom, move ASR to the secondary server rather than starving the game or TTS.

The published Windows build requires GCC/Clang (MinGW-w64 recommended); MSVC is documented as unsupported. Treat that toolchain requirement as a packaging constraint.

### 3. Nemotron 3 Diarization

The November 9, 2026 paper describes streaming Sortformer extended from four to eight speakers, with an arrival-order speaker cache. It reports 2.8× lower training memory, 2.2× faster training, and up to 6.4× inference throughput in its own evaluated configurations.

This is a diarization component, not a complete transcription system. STAR would still need ASR plus timestamp alignment and a speaker-to-utterance join. Compare it with VibeVoice's unified speaker-attributed ASR rather than assuming both should always run.

### 4. Multiparty interaction remains hard

MP-Bench (Findings of EMNLP 2026) evaluates turn-taking awareness, response appropriateness, and comprehension. Its evaluation of 12 voice agents reports multiparty comprehension at or below 22% and turn-taking near chance for real-time agents.

This supports a deliberate Social Director evaluation set with hard negatives:

- a viewer addresses another viewer, not STAR;
- two people overlap;
- a backchannel ("yeah", laughter, "right") should not seize the floor;
- a viewer repeats an earlier question;
- a correction is directed at another participant;
- STAR is speaking while a high-urgency game cue arrives;
- the transcript is low-confidence or the diarizer changes speaker slots;
- a stale event arrives after reconnect.

Measure false floor-taking and missed direct requests separately. A model that answers more often is not automatically more conversational.

### 5. Gaming and game creation

**SIMA 2:** Google DeepMind describes a self-improvement cycle using generated tasks, model-based feedback/reward estimates, and a bank of self-generated experience. The same research notes limits on very long-horizon tasks, goal verification, and short interaction memory. STAR should borrow the curriculum → attempt → score → save verified skill → held-out retest loop, not claim that a chat model alone has mastered gameplay.

**Roblox OpenGameEval:** the official benchmark runs agents in reproducible Roblox Studio sessions, separates observation tools from editing tools, and scores both the edited scene and a simulated Play session. Its paper reports 84 human-curated core tasks and finds that inspecting objects before editing is predictive of success. STAR Creator should inspect before mutation and prove behavior in Play mode.

**GameDevBench:** the ICML 2026 benchmark contains 333 multimodal game-development tasks. Its paper reports a 53.8% best result in the original evaluation, with task success falling from 51.4% on gameplay-oriented tasks to 33.0% on 2D graphics tasks. Visual/image/video feedback improved one evaluated GPT-5.4 configuration from 41.1% to 52.0%. STAR therefore needs screenshot/video feedback, asset inspection, and actual engine playtests—not only code compilation.

### 6. Inference and observability

UlaCache (October 21, 2026) explores unified logical addressing for sparse KV storage across GPU and CPU memory. Its reported gains are on multi-GPU H200/B300 configurations, so it is research inspiration, not a drop-in optimization for STAR's single consumer GPU. The transferable ideas are stable logical references, tier-aware placement, prefetch, and explicit accounting of transfer costs.

OpenTelemetry's current GenAI semantic conventions are still marked Development. Useful concepts include request duration, time-to-first-token, time-per-output-token, inference calls, and tool-call counts. STAR should map its existing local telemetry to these concepts where practical, but keep high-cardinality prompts, raw transcripts, viewer IDs, and credentials out of metric labels.

## Recommended STAR architecture

```text
audio source (explicitly consented)
        |
bounded PCM ring / source clock
        |
low-latency VAD + interruption detector ------------------+
        |                                                   |
streaming ASR adapter                                       |
        |                                                   |
session-local partial transcript / caption state           |
        |                                                   |
final utterance + speaker/time metadata                     |
        |                                                   |
speaker/addressee + intent classifier                       |
        |                                                   |
confidence / moderation / source policy                     |
        |                                                   |
RoomStreamHost -> RoomTurnDirector -> bounded room queue    |
        |                                                   |
STAR Brain -> sentence stream -> TTS -> measured playback -+
        |
avatar event derived from actual played audio
        |
OBS/VTube Studio adapter (separate explicit permissions)
```

### Adapter contract to implement later

A future adapter should publish typed events with:

- `stream_epoch` and monotonically increasing `chunk_index`;
- model/checkpoint revision and sample rate;
- audio start/end time on one documented clock;
- chunk text and whether it is provisional or final;
- session-local speaker label plus confidence;
- language / recognition confidence where supplied;
- explicit end-of-turn/finalization event;
- bounded error state and reset semantics.

No provider text or model output may grant tool permissions. Addressee classification is a prediction, not an authorization signal.

## Benchmark plan

Run matched, reproducible tests on the same owner-approved audio clips and same stream scenarios.

### ASR / diarization
- WER/CER on final utterances, not provisional chunks;
- speaker-attributed WER and speaker confusion;
- diarization error rate and overlap recall;
- timestamp boundary error;
- language/hotword accuracy;
- partial-caption update delay;
- finalization delay after end-of-turn;
- reconnect/epoch-reset correctness.

### Streaming / mixed load
- model cold-load and warm-up time;
- real-time factor (RTF), with target < 1 and headroom;
- audio chunk arrival-to-caption p50/p95/p99;
- end-of-turn-to-final-transcript p50/p95/p99;
- VAD barge-in detection latency;
- first generated token and first audible sample;
- TTS queue-to-DAC playback;
- CPU per-process utilization and GPU/VRAM residency;
- game frame-time p95/p99, OBS skipped frames, audio underruns;
- cancellation correctness and queue wait.

### Social quality
- direct-address precision/recall;
- third-party speech false-response rate;
- backchannel false-response rate;
- interruption precision and missed interruption rate;
- response appropriateness;
- long-session groundedness;
- viewer-message duplicate/replay handling.

### Gaming / creator
- task completion on held-out game states;
- survival / objective completion / score where available;
- skill transfer to a new map or game;
- verified-skill regression rate;
- Roblox scene checks and Play-session checks;
- visual defect count after screenshot/video review;
- successful save/reload and actual game-ending checks.

## Adoption gates

| Candidate | First experiment | Adopt only if |
|---|---|---|
| VibeVoice-ASR-Streaming-1.5B | Isolated secondary-worker test | Better speaker-attributed quality and acceptable chunk/final latency without starving game/TTS |
| VibeVoice-ASR-Streaming-7B | Server/large-GPU test | Material quality gain justifies memory and latency |
| VibeASR.cpp BitNet | Windows CPU test, 2 then 3 threads | RTF < 1 with game/audio headroom and acceptable WER |
| Nemotron 3 Diarization + existing ASR | Recorded overlap set | Lower speaker confusion than unified ASR at acceptable added latency |
| UlaCache-style tiered KV | Offline inference prototype | Measured benefit on STAR's actual serving backend; no adoption from H200/B300 claims |

## Implementation status and non-claims

This document is research and an adoption plan. It does not install model weights, add network services, add OAuth, enable microphone capture, connect VTube Studio/OBS, change model defaults, or claim a speedup.

The current PR's concrete code change also preserves the legacy injected engine-factory signature for ordinary microphone calls while passing `input_enabled=False` only for the new opt-in room-only path. This fixes the compatibility issue exposed by exact-head CI without changing default call behavior.

## Sources

- Microsoft VibeVoice repository and model matrix: https://github.com/microsoft/VibeVoice
- Microsoft VibeVoice streaming guide: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr-streaming.md
- VibeVoice-ASR-Streaming report (2 September 2026): https://arxiv.org/abs/2609.02812
- Official VibeVoice-ASR-BitNet CPU runtime and Windows benchmark: https://github.com/microsoft/VibeASR.cpp
- Nemotron 3 Diarization (9 November 2026): https://arxiv.org/abs/2611.12246
- MP-Bench, Findings of EMNLP 2026: https://aclanthology.org/2026.findings-emnlp.1437/
- Google DeepMind SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench, ICML 2026: https://proceedings.mlr.press/v306/chi26a.html
- UlaCache (21 October 2026): https://arxiv.org/abs/2610.29820
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md


## Additional full-duplex research: coordination, not just conversation

### Voice-Light — reversible playback and private speculation

The September 17, 2026 Voice-Light paper describes a cascaded full-duplex architecture with immediate acoustic onset, a causal adapter sharing a streaming-ASR encoder, reversible playback control, and private speculative response generation. Its central invariant is that uncertain work may begin early, but it becomes audible or durable only after explicit causal checks. Generated text/audio is tagged by generation and remains private until promotion; acknowledged/rendered playback, not generated text, is authoritative for durable conversation history.

The paper's locked evaluation is also a useful warning: a learned end-of-turn checkpoint with a 2.70% false-cutoff rate had only 12.53% end-of-turn recall, versus 95.60% for a Silero timing policy. The system therefore kept a hybrid controller rather than replacing timing with the learned detector. It reports a 758 ms median from final VAD endpoint to first server audio over 36 operator-run turns, but explicitly labels these as an instrumented case study, not a controlled population evaluation.

**STAR adoption:** retain the existing conservative VAD / endpointing baseline; use learned turn evidence as an additional signal, not an unvalidated replacement. Keep speculative response text and PCM isolated by generation ID. Promote only after turn commitment and policy checks. Continue using actual playback/DAC or client acknowledgements for captions, avatar lip-sync, cancellation truncation, and history.

### Joi-Bench-Task — track what is being done and what has been said

The November 9, 2026 Joi-Bench-Task paper evaluates whether a full-duplex agent can track:
- what task is currently executing;
- what has completed;
- what has already been communicated;
- what remains to be reported.

Its interactive simulator changes or withdraws requests during tool execution and interrupts the agent while it is speaking results. The paper reports that the best result-completion rate under request changes was 55%, and four of five evaluated agents had average information-omission rates of at least 23% after interruption.

**STAR adoption:** add a conversation/task coordination ledger to the unified runtime. Each work item should have a stable task ID and explicit states such as proposed, accepted, running, blocked, completed, cancelled, and reported. Spoken claims must reference completed evidence. If a viewer changes priorities while STAR is building a game or researching, the coordinator should update the queue without silently losing the earlier obligation. After interruption, STAR should resume only the uncommunicated remainder, not repeat already-audible content or omit completed work.

This is especially important for a VTuber who is simultaneously playing, answering viewers, and running background creation/research tasks.

### InteractionBench — four separate dimensions of natural streaming

InteractionBench (November 2, 2026) evaluates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness across conversations longer than twenty turns. Its harness uses 221 items across thirteen scenarios and evaluates both what the system says and how it manages the floor. The paper also highlights that client-heard timing includes network delay; server-side token timing alone is not an adequate user-perceived latency metric.

**STAR adoption:** maintain separate scorecards for:
1. floor control (respond / continue / wait / interrupt / resume);
2. spoken correctness and completion;
3. acoustic delivery (volume, whisper, prosody, intelligibility);
4. long-session grounding and memory use.

Record at least server first-token, first TTS chunk, first scheduled playback, and client/loopback-observed audible onset where available. Never label server TTFT as "time the viewer heard STAR."

## New task-coordination acceptance cases

Add these to future room-host and unified-runtime tests:

- A viewer asks STAR to pause a background build and answer a new question; the build state and checkpoint remain recoverable.
- A viewer changes a requested game feature while the creator agent is editing; the task ledger records the change and preserves any still-required work.
- STAR is interrupted halfway through a spoken progress report; after the follow-up she reports only the remaining facts.
- A task completes while STAR is speaking; the result is queued, not claimed as spoken.
- STAR says "I'm checking that" only after a work item actually starts.
- A queued message is cancelled by its owner or expires; it is removed from both queue and payload store.
- A response is interrupted after only part of its TTS was played; history and avatar state reflect only the played portion.
- A stale completion from an old task generation cannot overwrite the state of a newer retry.

## Additional sources

- Voice-Light (17 September 2026): https://arxiv.org/abs/2609.20995
- Joi-Bench-Task (9 November 2026): https://arxiv.org/abs/2611.12118
- InteractionBench (2 November 2026): https://arxiv.org/abs/2611.02430
