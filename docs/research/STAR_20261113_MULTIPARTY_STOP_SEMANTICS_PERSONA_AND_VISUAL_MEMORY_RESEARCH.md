# STAR Research — Multiparty Stop Semantics, Character Consistency, Visual Memory & Speech Runtime

**Research date:** 2026-11-13  
**Target:** `oncoursemail/Star-AI-Project`  
**Implementation:** typed human-resolution events that stop only the matching active room response  
**Status:** draft implementation; offline tests required on the exact PR head

## Executive finding

STAR's multiparty room runtime already distinguishes direct questions, corrections, backchannels, side conversations, game events, and high-confidence audio barge-ins. It can queue messages while speaking and cancels only a specific playback generation.

A recent benchmark exposes one missing conversational behavior: **stop speaking when another human has already resolved the request STAR was answering**. This is not the same as a generic interruption. If STAR keeps talking after a viewer or co-host has answered the question, she becomes socially intrusive and wastes speech time. If she stops for an unrelated side conversation, she loses useful context.

This update adds a typed, event-linked resolution signal and a dedicated `STOP` decision. It carries the original room-event ID into the active reply, then cancels only when a trusted final cue explicitly references that same event. It does not add ASR, diarization, addressee classification, Twitch/YouTube clients, or a model-driven classifier.

## 1. Duplex-MPE: silence and stopping are capabilities

Paper: https://arxiv.org/abs/2609.31948

Duplex-MPE (September 25, 2026) evaluates 2,000 multiparty scenarios with three or four human speakers and one assistant. The same request is paired across explicit and implicit addressing. It scores fresh response initiation, answer correctness, silence preservation, and stopping when a human resolves a request.

The benchmark's key lesson is that a voice agent should not maximize response frequency. A good agent sometimes remains silent, yields the floor, or stops an answer because the group has already resolved the question.

### STAR transfer

- Add an explicit `HUMAN_RESOLUTION` cue with `resolves_event_id`.
- Carry the triggering room event ID into the active response generation.
- Stop only when the resolution points to the exact request being answered.
- Ignore or continue on unrelated resolutions.
- Never treat a partial ASR hypothesis as a resolution.
- Require a final, confidence-qualified cue from the trusted host adapter.
- Keep the existing exact-response-ID cancellation fence.

The new stop action is intentionally separate from `INTERRUPT`: a human resolution should cancel the current answer but must not start a second answer to the resolution announcement.

## 2. CharDuplex: personality consistency must be evaluated over time

Paper: https://arxiv.org/abs/2609.34461

CharDuplex (September 28, 2026) studies character-conditioned full-duplex spoken dialogue. Its method constructs character-conditioned interaction data, checks dialogue and speech quality, and uses response-dependent simulated interaction to refine multi-turn consistency.

### STAR transfer

Treat STAR's persona as a versioned behavior contract, not a single style prompt:

- Stable identity and voice traits.
- Stable knowledge boundaries and uncertainty behavior.
- Consistent humor, warmth, energy, and conversational preferences.
- Situation-dependent expression and delivery.
- Explicit separation between fictional character lore and real-world facts.
- Consistency across corrections, interruptions, topic shifts, and long conversations.

Create paired evaluation conversations that test whether STAR preserves her character without repeating catchphrases or contradicting prior statements. Do not import a research checkpoint or fine-tune on unreviewed viewer chat. Persona quality must not override factual accuracy, platform rules, or transparent AI identity.

## 3. AdaptDuplex: adapt compute to the moment

Paper: https://arxiv.org/abs/2609.29217

AdaptDuplex (September 24, 2026) explores adaptive interaction windows, explicit listen/speak/control decisions, non-blocking cognitive consolidation, and multiple external reasoning flights.

### STAR transfer

Use a bounded two-speed interaction policy:

1. **Immediate loop:** low-latency acknowledgement, turn control, interruption handling, and short replies.
2. **Strategic loop:** longer reasoning, retrieval, research, and multi-step tool work.
3. **Consolidation loop:** summarize verified experiences and prepare future memory updates away from live deadlines.

The immediate loop must not wait for strategic reasoning. A background result must be revalidated against the current request before it can affect speech or actions. Extra reasoning is not automatically better: route it only when task complexity, uncertainty, or expected value justifies the latency and resource cost.

## 4. DMV-Bench: remember what was seen, not only what was written down

Paper: https://aclanthology.org/2026.emnlp-main.1892/

DMV-Bench (EMNLP 2026) studies visual memory through incidental cues in images. Its task contract prevents text leakage so that agents must remember information that was visible but not deliberately extracted into notes. The paper's DualMem approach combines visual and verbal memory codes.

### STAR transfer

STAR's memory evaluation should include:

- Incidental but task-relevant visual facts.
- Object and UI state changes across sessions.
- Which visual observation supports a remembered fact.
- Whether the fact is still current.
- Whether an observation was actually authorized to retain.

Store compact, task-relevant visual descriptors or references with timestamps and provenance—not indefinite raw screenshots. Do not build face recognition or persistent viewer identity profiles. Use opt-in capture, bounded retention, and explicit deletion/forgetting workflows. Evaluate visual-memory-on versus visual-memory-off using held-out future actions, not only recall questions.

## 5. Agent memory is a systems workload

Paper: https://arxiv.org/abs/2606.06448

The June 2026 systems characterization of long-horizon agent memory profiles construction, retrieval, and generation costs separately. It highlights that memory-write/consolidation cost can dominate even when retrieval quality looks good.

### STAR transfer

- Measure memory construction, retrieval, and generation separately.
- Batch consolidation during idle periods.
- Set per-session write budgets and tool-iteration caps.
- Prefer event-linked updates over rewriting the entire memory bank.
- Track freshness and correction provenance.
- Use memory only when it changes the next decision.
- Preserve a non-compacted evidence reference and reversible snapshots.

Memory compaction must be benchmarked for downstream task success and stale-fact reuse. Smaller memory is not automatically better memory.

## 6. NVIDIA NeMo-Speech.cpp: a candidate local speech stack

Official repository: https://github.com/NVIDIA/NeMo-Speech.cpp

NVIDIA describes NeMo-Speech.cpp as a native C++/ggml speech runtime. Its repository lists streaming ASR models, Nemotron 3 Diarization, Parakeet, MagpieTTS, VAD/endpointing, and a local HTTP/WebSocket server. Its published benchmark table reports results on an RTX 4090 and CPU; those figures are not predictions for STAR's RTX 4060 or a guarantee on the Windows host.

### STAR evaluation plan

Run it as an isolated, opt-in candidate against the current faster-whisper/Kokoro path:

- Same consented audio fixtures and transcript labels.
- Same sample rate, chunk duration, language, and hardware power profile.
- First partial transcript and final transcript latency.
- Word error rate and speaker-attribution error.
- CPU, RAM, VRAM, and GPU contention while a game and OBS are active.
- Audio underruns and game frame-time p95/p99.
- Cold-start and warm-start behavior.
- Windows install/upgrade/uninstall and model checksum verification.

Do not replace the default voice stack until the candidate wins a paired accuracy/latency/mixed-load test on the actual target PC. A 100M diarization model and a 0.6B streaming ASR model are not free: measure their memory and scheduling costs.

NVIDIA's September 2026 technical-blog update identifies Nemotron 3 Diarization as its newer diarization release and states support for up to eight speakers: https://developer.nvidia.com/blog/author/taejinp  
Model card and license: https://huggingface.co/nvidia/Nemotron-3-Diarization

## 7. Inference speed: use measurements, not leaderboard assumptions

Dataset: https://llm-speed.com/ (version 2026-11-06)

The dataset reports 803 results across 116 models and 19 hardware configurations. It is useful for candidate discovery, but its own methodology notes that signed runs establish provenance, not independent hardware verification, and some GPU comparisons use different machines or builds.

For STAR, use the dataset to shortlist model/quant candidates, then benchmark locally:

- Prompt prefill and time to first token.
- Decode tokens/second at several context lengths.
- First non-empty content and first audible playback.
- p50/p95/p99 under one and multiple concurrent requests.
- KV-cache VRAM and peak system RAM.
- Game frame-time, OBS skipped frames, and audio underruns.
- Held-out answer quality and task success.

Keep stable prompt prefixes byte-identical for cache reuse. Change one inference variable at a time. Do not assume KV-cache compression is faster: it may reduce memory while increasing dequantization work or reducing quality. No speculative-decoding or TurboQuant fork should become a default without model-specific paired tests and license review.

## 8. Implementation in this PR

### Added behavior

- `CueIntent.HUMAN_RESOLUTION` requires a bounded `resolves_event_id`.
- A room response remembers the event that caused it.
- `RoomTurnDirector` emits `RoomAction.STOP` only when the final resolution references the active response's exact triggering event.
- An unrelated resolution returns `CONTINUE`.
- A response without a linked room-event ID cannot be stopped by an ambiguous resolution.
- `CallSession` maps the stop decision to a response-generation-fenced cancellation reason of `room_human_resolved_request`.
- The resolution announcement is not spoken as a second reply.

### Not implemented

- Audio recognition, speaker diarization, addressee detection, or resolution classification.
- Twitch EventSub or YouTube Live Chat adapters.
- VTube Studio/OBS transport changes.
- Model training, weight changes, default routing, or GPU settings.
- Persistent viewer profiles or raw-media retention.

The trusted provider/ASR adapter must classify a resolution and link it to an existing event before submitting it. Until then, the new behavior is an offline-tested contract, not a live-stream capability.

## 9. Acceptance tests

1. Matching human resolution stops only the exact active response.
2. Unrelated resolution does not interrupt.
3. Resolution without a linked active request does not interrupt.
4. Game-originated resolution cannot stop a spoken response.
5. Missing or malformed event references fail validation.
6. A stop action never creates a second answer.
7. Existing direct barge-in, correction, queueing, and backchannel tests remain unchanged.
8. Live acceptance later measures false stops, missed stops, silence preservation, answer correctness, and response latency on consented multiparty rehearsal data.

## Sources

- Duplex-MPE: https://arxiv.org/abs/2609.31948
- CharDuplex: https://arxiv.org/abs/2609.34461
- AdaptDuplex: https://arxiv.org/abs/2609.29217
- DMV-Bench: https://aclanthology.org/2026.emnlp-main.1892/
- Agent Memory systems characterization: https://arxiv.org/abs/2606.06448
- NVIDIA NeMo-Speech.cpp: https://github.com/NVIDIA/NeMo-Speech.cpp
- NVIDIA Nemotron 3 Diarization model: https://huggingface.co/nvidia/Nemotron-3-Diarization
- LLM speed dataset: https://llm-speed.com/
