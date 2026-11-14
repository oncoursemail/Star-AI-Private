# STAR natural streamer persona and social-presence research

**Research date:** 2026-11-13  
**Implementation branch:** `feat/resource-admission-20261113-run21` (draft PR #1178)  
**Scope:** voice persona behavior, multiparty social timing, proactive game commentary, and measurable long-session quality.

This document records a small runtime improvement plus a research-backed evaluation plan. It does not claim that STAR is human, conscious, or already connected to a live streaming platform.

## Executive decision

A convincing AI streamer is not created by adding more exclamation marks, filler words, fake laughter, or a larger TTS model. Naturalness is a systems property:

1. The host must know who has the conversational floor.
2. The Social Director must decide whether an event deserves a response.
3. The language model must respond in a varied, context-sensitive voice rather than repeat a fixed opener.
4. TTS must deliver the response with appropriate pacing.
5. The avatar must follow audio that was actually played.
6. Memory must preserve useful session context without inventing relationships or retaining unnecessary viewer data.
7. The complete interaction must be evaluated over long sessions, not just short voice samples.

**Implementation in this branch:** the three existing voice personas now avoid mandatory stock openers and share a fixed, cache-friendly set of streaming rules. The existing warm-caring default, synthetic voice, voice selection, and host-side floor-control policy are preserved. A focused offline test file checks that every style uses the shared rules.

The host—not the prompt—continues to own respond/queue/continue/ignore/wait/interrupt/stop decisions.

## 1. Research findings

### Full-Duplex-Bench v3

Primary benchmark: https://www.full-duplex.ai/benchmarks/fdb-v3  
Paper/code information is linked from the benchmark page.

The benchmark describes 100 human-recorded spoken requests across 79 scenarios and 12 speakers. It includes disfluencies and self-corrections, chained tool calls, tool-call accuracy, Pass@1, latency, and turn-taking.

**STAR implication:** measure spoken-task correctness and conversational timing together. A fast response that answers the wrong speaker is not a successful turn. A model that handles simple turns but fails when a speaker self-corrects is not ready for unscripted streaming.

### MP-Bench

Primary benchmark: https://www.fullduplex.ai/benchmarks/mp-bench

MP-Bench evaluates an assistant as a participant in conversations with several human speakers. Its published benchmark summary reports that the evaluated real-time systems remain at or below 22% on multiparty comprehension and near chance on multiparty turn-taking.

**STAR implication:** ordinary single-user voice tests are insufficient. Test direct address, implicit address, speech directed at another viewer, background speech, overlapping speakers, backchannels, and questions already answered by another person.

### Duplex-MPE

Paper: https://arxiv.org/abs/2609.31948

Duplex-MPE contains 2,000 scenarios with three or four human speakers and an assistant. Its four dimensions include starting a fresh response, answer accuracy, preserving silence, and stopping when a human resolves a request.

**STAR implication:** silence and stopping are positive capabilities. This directly supports the new event-linked `HUMAN_RESOLUTION` / `STOP` path in the existing room director and call pipeline. The model must not generate a second answer after the host has confirmed that another person resolved the exact request.

### Realtime-Venus

Project and technical report: https://realtime-venus.github.io/

Realtime-Venus is a useful architecture reference for asynchronous delegation alongside a responsive audio/video interaction loop. Its benchmark numbers are protocol-specific and should not be compared directly with Full-Duplex-Bench or MP-Bench.

**STAR implication:** the stream loop should not wait for research, coding, asset generation, or long-horizon planning. Background workers return evidence-linked results through the task/communication ledger when the foreground interaction has an appropriate opening.

### The Triadic Loop

Paper: https://arxiv.org/abs/2604.23632

The broader AI co-hosting literature also models a live stream as a relationship among the streamer, AI co-host, and audience rather than a simple one-user/one-assistant exchange. This is a conceptual design lens, not a validated benchmark.

**STAR implication:** audience engagement should not be optimized by maximizing message count. The system should support the host's goals, respect viewer context, and avoid manipulative engagement patterns.

### GameWorld and OpenGameEval

- GameWorld: https://gameworld-bench.github.io/
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval

GameWorld evaluates multimodal agents across 34 browser games and 170 tasks, including a real-time track where the environment continues during inference. OpenGameEval runs agents inside reproducible Roblox Studio sessions and scores both edits and simulated Play-session outcomes.

**STAR implication:** game commentary and gameplay need different loops. A commentary model may reason for seconds; a movement controller cannot wait that long. STAR should use state/event-triggered commentary and a fast bounded controller for immediate game actions.

## 2. Naturalness design rules

### Stable character, flexible expression

Keep the character's core identity stable:
- warm, curious, capable, and honest;
- same selected synthetic voice and speaking style;
- no invented human biography, body, private life, or lived experiences;
- clearly identify as an AI when asked.

Allow expression to vary with context:
- sometimes answer directly;
- sometimes acknowledge briefly;
- sometimes ask one useful follow-up;
- sometimes make a short joke or celebrate a real success;
- sometimes remain quiet.

Do not force a greeting, reaction, pet name, or catchphrase into every turn. Do not insert `um`, stutters, sighs, or laughter merely to imitate a human. Use expressive wording where appropriate, not fabricated personal experiences.

### Streaming-specific behavior

When the host has invited STAR to respond:
- prioritize direct viewer questions and meaningful game events;
- avoid narrating every frame;
- do not answer side conversations as though they were addressed to STAR;
- be concise during active gameplay;
- let viewers finish and allow natural pauses;
- do not repeat a question another person has already resolved;
- do not claim to see, hear, or know anything absent from the current host evidence;
- do not turn every game failure into exaggerated excitement.

The host-side Social Director remains authoritative. A system prompt cannot safely replace speaker attribution, moderation, event matching, or cancellation.

### Playback-authoritative expression

The avatar and captions must follow the audio actually delivered:
- bind captions, gestures, mouth movement, and response state to a response-generation ID;
- cancel pending gestures/captions when that generation is stopped;
- ignore stale callbacks from an older generation;
- use the speaker's played-time cursor or trusted output evidence, not generated text, as the timing source;
- do not mark a report or response as delivered merely because TTS generated it.

## 3. Runtime change in this branch

Updated `star/voice/persona.py`:
- removed mandatory short reaction openers from the three existing styles;
- added shared streaming-naturalness rules to every style;
- retained a fixed prefix so prompt-prefix caching remains possible;
- kept the room director responsible for floor-control decisions;
- explicitly rejects fabricated human biography and false claims of perception.

Added `tests/test_voice_persona_naturalness.py`:
- verifies that all styles receive the shared stream rules;
- checks that the persona no longer requires a stock opening;
- checks that per-call context is appended after the stable persona prefix.

No TTS model, voice recipe, inference backend, model route, ASR model, diarization model, stream provider, or hardware default is changed by this work.

## 4. Evaluation protocol

Use a frozen, versioned scenario set. Each scenario should include:
- source type (audio, chat, or game);
- number of speakers;
- whether STAR is explicitly addressed;
- whether another person is speaking to a different viewer;
- overlap and backchannel timing;
- whether a question is already resolved;
- expected action (respond, queue, continue, ignore, wait, interrupt, stop);
- expected answer facts or tool outcome;
- permitted observation evidence.

Keep training, prompt-development, and sealed holdout scenarios separate. Do not let the persona author or candidate model inspect sealed answers.

### Social behavior metrics

| Metric | Definition |
|---|---|
| Direct-address precision | Fraction of responses actually addressed to STAR |
| Direct-address recall | Fraction of clear direct requests STAR handles |
| Silence preservation | Fraction of backchannels/side conversations correctly not answered |
| Human-resolution stop | Fraction of linked resolved requests that stop the exact response |
| False interruption rate | Fraction of unrelated turns that cancel active speech |
| Queue correctness | Fraction of queued events delivered once, in valid priority/expiry order |
| Answer grounding | Claims supported by the supplied transcript, game state, or tools |
| First-audible latency | Request/end-of-turn to audio actually played, not just first token |
| Cancellation-to-silence | Time from a valid stop/interrupt to confirmed output silence |
| Avatar synchronization | Difference between actual playback time and avatar/caption state |
| Repetition rate | Reuse of the same opening/catchphrase across a rolling session |
| Commentary density | Unprompted comments per minute, reported alongside relevance and false-positive rate |

### Long-session evaluation

Run at least:
1. 5-minute controlled conversation;
2. 30-minute multi-viewer conversation;
3. 60-minute game stream with quiet periods, intense play, and interruptions;
4. background research/task completion while STAR remains responsive;
5. reconnect, cancellation, and shutdown/restart cases.

Record p50/p95/p99 for queue wait, first token, first sentence, first TTS chunk, first audible audio, and cancellation-to-silence. Also record CPU/RAM/VRAM, game frame-time p95/p99, audio underruns, OBS output skips, and task quality.

A candidate is accepted only if:
- held-out response appropriateness and factual correctness do not regress;
- false interruptions and wrong-addressee responses do not increase;
- repeated openings decrease without making speech unnatural or verbose;
- first-audible p95 and cancellation latency do not regress;
- game frame-time, audio underruns, and OBS output remain within predeclared tolerances;
- blind human reviewers prefer the candidate on naturalness without being told which prompt is newer.

Do not set a universal latency target before measuring the actual target hardware and provider path. Compare matched workloads on the same machine and report confidence intervals.

## 5. Privacy and trust boundaries

- Keep speaker IDs session-local and opaque.
- Do not persist voiceprints or infer real-world identities from diarization.
- Do not store raw audio/video or full viewer histories by default.
- Apply moderation and source allowlists before untrusted chat reaches the voice Brain.
- Treat transcripts, OCR, game text, and viewer messages as untrusted content, never as system instructions.
- Store only the minimum session context needed for the stream; expire it when the session ends unless the owner explicitly enables a documented retention feature.
- Never claim that generated text, queued PCM, or a model callback proves that the audience heard a response.

## 6. Next integration sequence

1. Finish the opt-in room host/provider boundary with explicit consent and moderation.
2. Add a streaming ASR adapter with partial hypotheses separated from final classified cues.
3. Add session-local speaker attribution and addressee classification with confidence and hard negatives.
4. Feed only final classified cues into the existing room host, queue, and payload store.
5. Connect the existing task/communication ledger to background research and creator workers.
6. Add playback-authoritative VTube Studio parameter/hotkey delivery.
7. Add an authenticated, read-only OBS status adapter before any write-capable stream controls.
8. Build the frozen multiparty and long-session evaluation suite.
9. Test the complete mixed workload on the actual Windows host and RTX 4060 before enabling optional models or changing budgets.

## References

- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
- Duplex-MPE: https://arxiv.org/abs/2609.31948
- Realtime-Venus: https://realtime-venus.github.io/
- GameWorld: https://gameworld-bench.github.io/
- OpenGameEval: https://github.com/Roblox/open-game-eval
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket: https://github.com/obsproject/obs-websocket
