# STAR — Multi-Party Floor Control, Natural Streaming, and Generalist Runtime Research

**Research date:** 2026-11-10  
**Implementation branch:** `feat/multiparty-floor-control-20261110-auto11`  
**Base:** `feat/stream-event-timeline-20261110-auto11` (PR #1103)  
**Status:** Draft engineering work; no production release or live broadcast change.

## Executive finding

STAR already has separate foundations for semantic end-of-turn detection, cross-modal event alignment, active-listening cues, full-duplex evaluation, speech pacing, long-session voice health, game/OBS QoS, and model quality-versus-speed gating. The missing connection identified in this review was **multi-party addressee control at the actual spoken-event ingress**.

A diarization label can tell a host that two utterances came from different voices. It does not prove that either person is speaking to STAR, and it is not a real-world identity. Without a separate addressee/floor decision, a streamer can answer side conversations, talk over guests, or miss the social floor.

This change adds an opt-in, content-free floor gate and connects it to `StreamBrainGovernor.offer()`. It only gates host-classified spoken viewer questions/comments. Ordinary chat, game events, and the existing authenticated-owner interruption path remain unchanged.

## Research findings

### 1. Multi-party conversation is a distinct capability

**MP-Bench (Findings of EMNLP 2026, October 2026)** evaluates turn-taking awareness, response appropriateness, and complementary comprehension in multi-party voice settings. Across 12 voice agents, real-time systems score at or below 22% on multi-party comprehension and remain near chance on multi-party turn-taking. This is strong evidence that dyadic turn detection is not enough for a streamer who hears multiple people.  
Source: [ACL Anthology — MP-Bench](https://aclanthology.org/2026.findings-emnlp.1437/)

**Full-Duplex-Bench-v3 (April 6, 2026)** uses real human audio with five disfluency categories and chained API tasks. It evaluates tool accuracy, interruption/turn-taking behavior, and latency separately. Its reported systems show that a fast response can still have poor turn acceptance, while a conservative cascaded system can take much longer. Self-corrections and hard multi-step tasks remain failure modes.  
Source: [arXiv:2604.04847](https://arxiv.org/abs/2604.04847)

**LiveKit speaker diarization guidance** explicitly distinguishes diarization from identification: session-local labels such as S1 only indicate that two utterances came from the same voice in that session. Similar voices, overlap and noise can merge or split speakers. Background-transcript suppression also does not necessarily suppress audio-level interruptions. STAR therefore uses short-lived numeric speaker slots, never names or cross-session voice identities, and defaults to silence/hold when overlap or confidence is poor.  
Source: [LiveKit — Speaker diarization](https://docs.livekit.io/agents/models/stt/diarization/)

**LiveKit interruption handling** also highlights a critical history invariant: after an interruption, conversation history should contain only the speech the listener actually heard. STAR's existing host-side audible-turn and interruption controls remain authoritative; this floor gate does not replace them.  
Source: [LiveKit — Turns and interruptions](https://docs.livekit.io/agents/logic/turns/)

### 2. Foreground interaction must stay separate from background reasoning

**Realtime-Venus (September 12, 2026)** describes two cooperating loops: a live perception/conversation frontend and an asynchronous delegation harness. The foreground continues interacting while background tasks run, and delegated results return to the same conversation with their original context.  
Source: [Realtime-Venus technical report](https://arxiv.org/abs/2609.13814)

STAR should preserve this separation:
- **Foreground:** turn-taking, owner/guest floor, urgent game events, short grounded responses, audio stop/interruption.
- **Background:** research, multi-step tool work, game strategy analysis, code generation, long-memory retrieval and asset creation.
- **Return path:** a background result is revalidated for freshness, relevance and permission before it can become a spoken response.

The new floor gate belongs in the foreground ingress path; it must not wait for a research agent or model-generated explanation.

### 3. Long-term memory should be temporal and evidence-linked

**APEX-MEM (ACL 2026)** uses an entity-centric property graph, append-only temporal storage and query-time resolution of conflicting or evolving facts. The paper reports 88.88% on LOCOMO and 86.2% on LongMemEval. The design lesson for STAR is to preserve historical facts and resolve the current answer at retrieval time rather than overwrite history or dump an ever-growing transcript into the prompt.  
Source: [ACL Anthology — APEX-MEM](https://aclanthology.org/2026.acl-long.749/)

Recommended STAR memory evolution:
- append-only event/claim history;
- explicit entity and project scope;
- validity interval and observation time;
- provenance class: user statement, public source, host observation, experiment, or inference;
- confidence and contradiction links;
- retrieval-time resolution;
- separate private viewer context from broadcast-approved public memory;
- compact live retrieval, deeper background retrieval.

This is a roadmap recommendation, not part of the current code change.

### 4. Persistent engineering skill requires multi-round evaluation

**EvoCode-Bench (May 22, 2026)** evaluates 26 stateful coding tasks over 227 rounds. Single-round performance often exceeds multi-round persistent execution by 22–40 points; the paper reports substantial regression as requirements accumulate. This supports cumulative tests, durable workspace state, and long-horizon regression checks for STAR's self-improvement and game-creation agents.  
Source: [arXiv:2605.24110](https://arxiv.org/abs/2605.24110)

STAR should grade a coding/game-building agent on whether it preserves previous requirements across multiple changes—not just whether one isolated patch passes.

### 5. Game mastery must be measured under a live clock

The existing STAR game-learning work already distinguishes real-time gameplay from paused reasoning, balances scenarios, and protects the 8 GB GPU with optional worker leases. Continue to measure:
- capture-to-action latency;
- action acknowledgement and deadline misses;
- per-scenario progress/win rate;
- skill transfer to held-out maps/mechanics;
- performance with OBS, TTS and avatar rendering active;
- recovery after death, respawn, map changes and unexpected mechanics.

Do not use paused-only success as evidence that STAR can play a live game well.  
Related research: [Gym-Anything-RT](https://arxiv.org/abs/2610.37567)

## Implementation

### New module: `star/stream_multiparty_floor.py`

Adds four types:

- `FloorObservation`: bounded, content-free host receipt containing an opaque turn ID, current floor-session epoch, monotonic sequence/timestamp, ephemeral speaker slot, addressee class, speech-act class, confidence values, active-speaker count, and complete/interrupted flags.
- `FloorPolicy`: configurable freshness, clock-skew, confidence, overlap and capacity limits.
- `FloorDecision`: one-use host-side result: `respond`, `listen`, `backchannel`, `silence`, or `hold`.
- `StreamMultipartyFloorGate`: session-scoped replay protection, sequence checking, monotonic-clock fault latch, bounded pending/seen sets and deterministic decision policy.

### Decision policy

| Evidence | Decision |
|---|---|
| Fresh, complete, confidently addressed question/request/correction to STAR; one active speaker | `respond` |
| Addressed to another person | `silence` |
| Addressed to the group | `listen` |
| Side conversation | `silence` |
| Backchannel | `backchannel` (non-spoken cue only; no TTS authorization) |
| Turn still in progress | `listen` |
| Unknown addressee, low confidence, overlap, interruption, stale/future receipt | `hold` |

The initial policy defaults are deliberately conservative and **not empirically calibrated**:
- maximum receipt age: 1,500 ms;
- future tolerance: 25 ms;
- signal/receipt timestamp skew: 250 ms;
- speaker confidence: 0.80;
- addressee confidence: 0.82;
- speech-act confidence: 0.75;
- maximum active speakers for direct response: 1;
- pending receipts: 64;
- seen turn IDs per session: 512.

A clock regression latches the gate until the session is disabled and re-enabled. Capacity exhaustion rejects new observations rather than evicting replay history and making an old receipt reusable.

### Live-path integration

`StreamBrainGovernor` now accepts an optional `multiparty_floor` dependency. When configured and owner-enabled:
1. the native host reads the current `multiparty_floor_session_epoch` from governor status;
2. it creates a session-local `FloorObservation` from its diarization and addressee classifier;
3. it calls `offer(..., spoken_turn=True, floor_observation=..., moderated=True)`;
4. the governor requires the exact same signal ID, current session epoch, monotonic sequence, fresh timestamp, <=250 ms signal/receipt skew, and an allowed `respond` decision;
5. only then does the event enter the existing `StarStage` queue;
6. the host can consume the exact one-use `FloorDecision` through `take_floor_decision(signal_id)`. A `backchannel` result can be routed to the existing non-spoken listener/avatar cue path; it never authorizes TTS. A response decision is cleared if the stage itself rejects the event or the session changes.

The floor gate is optional, so existing callers retain their previous behavior unless they explicitly mark a turn as spoken. If a spoken turn is requested without the configured gate or a receipt, the event is rejected.

The gate does **not**:
- perform diarization, ASR, addressee recognition or audio capture;
- identify a person or recognize an owner by voice;
- store transcripts, audio, voiceprints, names or viewer IDs;
- interrupt currently playing audio;
- authorize TTS, avatar movement, OBS, game input or tools;
- override the existing authenticated-owner barge-in path;
- affect ordinary chat, game danger/success events or non-spoken viewer events.

A host-provided confidence value is not cryptographic proof. The native host must authenticate its adapters and supply realistic confidence/calibration data. The model and viewer text must never be able to construct or modify these receipts.

## Broader STAR capability roadmap

### VTuber / streaming
- Integrate a streaming diarization provider or local diarization model behind the existing host boundary.
- Add addressee detection using direct address, conversation context and explicit handoff cues; never treat speaker labels as identities.
- Evaluate side conversations, group questions, backchannels, false interruptions, self-corrections, overlapping speech and speaker changes separately.
- Keep silence as a valid action; avoid filler loops and fabricated laughter/emotion.
- Continue measuring first-audible PCM, interruption-to-silence, voice consistency, repeated commentary, OBS drops and audio underruns.
- Keep foreground response independent from research/delegation.

### Gaming
- Maintain reflex, tactical, strategic and learning policies with separate deadlines.
- Use live-clock, scenario-balanced, held-out evaluations.
- Build reusable skills for navigation, camera control, aiming, timing, inventory, objectives, recovery and game-specific mechanics.
- Learn from practice receipts only; keep validation/holdout evidence sealed.
- Keep optional VLM, training and rendering workers behind the existing physical-stop GPU lease boundary.

### Game creation and general intelligence
- Use inspection-first project understanding, isolated builds, static checks, visual comparison, playtesting and cumulative regression tests.
- Extend skill transfer across Roblox, Minecraft, Blender, animation, VFX, audio and general software.
- Build a temporal evidence graph for facts, experiences, procedures, corrections and evolving project decisions.
- Evaluate factual accuracy, source attribution, uncertainty, temporal updates and abstention independently.
- Preserve full evidence archives; keep model-facing summaries small and source-linked.

### Inference speed
- Continue paired baseline/candidate measurements: TTFT, first audible output, ITL, end-to-end p50/p95, tokens/sec, queue delay, failures and cold start.
- Benchmark prompt-prefix caching separately from decode acceleration.
- Compare speculative decoding on/off under identical weights, context and request settings; acceptance ratio alone is not a speedup.
- Test quantization and CPU/GPU placement under the actual 8 GB VRAM budget.
- Run mixed-load tests with game rendering, OBS, TTS, avatar, vision and background reasoning together.
- Never change model routing from synthetic or aggregate-only evidence.

## Verification and acceptance

New focused tests cover:
- direct address, other-person address, group address and side conversation;
- request/question/correction/backchannel/statement distinctions;
- low speaker/addressee/act confidence;
- overlap, incomplete and interrupted turns;
- stale and future timestamps;
- sequence, session and event replay;
- clock regression latching;
- bounded capacity and session reset;
- aggregate-only status;
- governor ingress integration, timestamp binding, moderation requirement, ordinary chat compatibility and owner-interrupt compatibility.

**Acceptance still required on the actual host:**
1. connect a trusted streaming diarization/addressee adapter;
2. calibrate thresholds on owner-consented, independently annotated multi-party sessions;
3. hold out complete sessions, not random utterance fragments;
4. report response precision/recall, false-address responses, missed-addressed turns, group/side-conversation response rate, p50/p95 response delay and overlap handling;
5. verify owner interruption and physical audio stop remain independent;
6. run a private, non-broadcast 30–60 minute game + OBS + TTS + avatar rehearsal;
7. measure CPU/RAM/GPU/VRAM, game frame time, OBS drops, audio underruns and first-audible latency.

No live diarization adapter, model, audio device or Windows stream was run in this change. The thresholds are starting values only; no measured human-likeness, intelligence, inference-speed or gameplay improvement is claimed.
