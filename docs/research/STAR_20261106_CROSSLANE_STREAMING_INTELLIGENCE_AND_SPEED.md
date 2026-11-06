# STAR AI — cross-lane private-rehearsal integrity and next intelligence / speed upgrades
Date: 2026-11-06. Scope: additive, default-off local evaluation. Draft PR stacked on #1026; **not a live-stream or gameplay authorization**.

## What was actually implemented

The existing `stream_private_rehearsal_scorecard.py` checks five important but mostly independent evidence families. A failure remained: valid-looking but contradictory reports could be accepted as a private-rehearsal review candidate. For example, a ten-second OBS counter window could be paired with a much longer decoded recording, or a 300-frame OBS output could be paired with a 220-frame recording. Separate lane verdicts are not evidence of a coherent real-time session.

New `stream_private_rehearsal_alignment.py` now checks *cross-lane consistency* before `candidate_for_owner_review`:
- Bounded, finite recording duration, frame rate, dimensions, and selected audio-track index.
- Private recording duration aligned to the monotonic OBS performance-counter window (tolerance max 1.25 seconds or 10%).
- Media frame count aligned to the OBS output frame delta (tolerance max 12 frames or 12%).
- A/V auditor duration aligned to the decoded media duration (tolerance max 0.35 seconds or 3%).
- A/V frame count appropriate to the analyzer's 30-Hz downsampling (tolerance max 5 frames or 7%).
- A/V sample-count agreement and finite alignment statistic, bounded mouth lag and calibration metric.
- A forged `verified_humanlike` or `automated_deployment_allowed` field is a contradiction, never a reason to promote.

Each mismatch produces a **fixed non-sensitive reason code**, defers the scorecard and never exposes raw audio, footage, player information or filenames. Good tolerance cases remain eligible for owner review. This is a synthetic offline check only: two perfectly forged reports could still be mutually consistent. Their shared provenance remains unverified without a trusted capture host, immutable recording fingerprint, and private owner review.

## New evidence gathered

- 2026-11-06 ~17:05 Central on connected Windows Main: **RTX 3060 Ti, 8192 MiB reported total, 6510 MiB free, 45% utilization** at a single read-only instant; available VRAM has varied dramatically in other snapshots. GPU utilization is not a proxy for VRAM residency. This is not a speed benchmark. No new models were loaded.
- Connected Linux development host remained about 95% full (roughly 11 GB available); avoid caching model checkpoints or generating enormous game recordings there without a storage budget.
- Offline verification: cross-lane and sibling Windows/OBS/A/V/native-game tests (nine relevant areas); expanded result and version should be included in PR notes, not treated as proof of real recorded gameplay.

## The higher-intelligence architecture (specific implementation order)

1. **Immediate game reflex (< interactive input deadline):** authoritative frame or signed game state -> extremely small skill policy / action head -> OS-native input watchdog -> next host-observed state. Do not place a large speech/chain-of-thought model in the reflex critical path. A frame timestamp must remain valid until actual actuation, not just initial inference.
2. **Tactical reasoning (hundreds of ms to seconds):** a capable model receives a compact state digest and proposes a short-horizon strategy (cover, timing, map route, ability combo, resource management); it cannot bypass reflex deadlines, input release, or private-game scope. Use event-triggered planning rather than recomputing on every game frame.
3. **Slow learning (minutes to days):** the gaming curriculum proposes harder tasks and strategy variants; `game_state_transition_witness`, `game_transfer_eval`, and `game_holdout_seal` distinguish verified training from unseen tests. Store causal summaries, not raw sensitive captures or claimed wins.
4. **Decision diversity:** synthesize 4–8 candidate tactical options when hardware is idle, run them against isolated reproducible seeds, and select a passing candidate by an independent evaluator. Never use unvalidated synthetic game outcomes as success labels.
5. **Transfer evaluation:** choose unfamiliar games, changed UI scales, novel maps and mechanics; report frozen test performance, attempts and median frame-to-action latency. A higher reward on previously seen levels is not proof of general intelligence.

Gym-Anything-RT (Aggarwal & Welleck, **2026-10-27**, https://arxiv.org/abs/2610.37567) reports a large gap between real-time and paused minigames. It contains 100 real-time minigames and, in one stated comparison, a model's success is 9% real-time versus 75% paused. Those results do **not** describe STAR; they explain why moving the planner off the immediate reflex loop matters.

## Streaming naturalness: behavior that feels responsive rather than falsely human

- **Listen while speaking:** isolate the viewer input track, support detected end-of-utterance and barge-in, *duck and stop* a pending TTS segment on a true interruption, then resume only if the utterance still applies to the current game moment.
- **Choose when to speak:** gameplay urgency and teammate speech receive priority over generated chatter. Skip low-information or stale remarks. Embrace quiet listening, low-intensity gaze/idle motion and relevant backchannels when socially appropriate.
- **Ground expression:** speech prosody and mouth animation must be derived from audible output, not the generated script. Game celebrations only follow signed/trusted observations, not model predictions. Avoid claiming to have emotions, memories, wins or relationships without grounds.
- **Voice/rig experiments:** compare CPU Pocket TTS, existing local voice stack and full-duplex research as alternative candidates; choose on measured first-audio p50/p95, interruption stop time, prosody listener quality, avatar-sync drift, CPU cost, and real game FPS. Do not blindly migrate to a heavy full-duplex model that exceeds 8 GB VRAM.
- **Persistent character identity:** bounded opt-in preference journal; distinguish verified episodic memories, character lore and uncertain inferences. Redact viewer PII, define TTL, and give viewers a visible AI disclosure. No pretend-human deception.

Relevant primary research: Microsoft Proact-VL (**May 2026**, https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/), especially *when* to comment; NVIDIA DyaPlex (**June 2026**, https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) for duplex speech-motion. These are architecture leads, not integrated model weights or verified human-equivalent performance.

## Speed plan for the RTX 3060 Ti / RTX 4060 8 GB class

- **Admission gate:** measure **free VRAM** and CPU/RAM pressure at the *moment* of scheduling a new inference workload, with hysteresis. Preserve VRAM for the game, OBS compositing/encoding and avatar. When insufficient, route TTS/secondary reasoning to CPU or a separate machine; a free-VRAM snapshot is not a reservation.
- **Prompt/cache lane:** stable system prefix and tool schemas, per-session KV isolation, a short rolling gameplay summary, retrieval over verified Star lessons. Never allow cached prompts to mix viewers' private data or holdout answers.
- **Draft-token ablation:** test baseline decoding versus n-gram and small draft models supported by llama.cpp; report acceptance length, VRAM peak, TTFT, tokens/s, p95 latency and game/OBS impact under the same fixed prompts and random seeds. A speculative setup that improves token throughput but reduces real-time frame responsiveness loses.
- **Local TTS:** Kyutai Pocket TTS documents CPU execution, streaming chunks and compact small models (https://kyutai-labs.github.io/pocket-tts/); their public timings are not STAR's timings. Run local A/B measurements before choosing a voice engine.
- **Resource orchestration:** separate high-priority game input and render lane, medium audio playback/voice, lower-priority research/sandbox experiments, bounded queue depth and cancellation. Stale commentary should be discarded rather than piling up.

A successful performance claim must report *end-to-end* capture -> perception -> decision -> physical input release, as well as speech-to-first-audible-sample and OBS render/output loss. Never equate high `llama-server` tokens/s with playing skill or livestream quality.

## Roblox creation and cross-domain skills

The **2026-11-04** Roblox Studio MCP/Open Cloud expansion provides scoped external tools, asset import, permissions and project management (https://create.roblox.com/docs/studio/mcp-open-cloud). Use a separate test experience with minimal scopes. Studio MCP can inspect/create Luau and run bounded playtests; **do not** grant production datastores, publication, monetization edits or live-player operations to autonomous practice. Build -> Luau analyze -> isolated Studio run -> screenshot/functional comparisons -> repair -> verify holdout. Failed tests become a practice challenge only after scope and contamination checks.

Extend the same loop to other generalist skills: browser automation, code refactoring, Blender, 2D/3D asset import, VFX/animation, desktop UI, ordinary factual retrieval, research source checking and audio editing. The most useful measure is verified tasks completed per unit time and compute, not sheer number of self-generated lessons.

## Owner-review acceptance experiment (the next real milestone)

1. On Windows, explicitly approve a private, non-broadcast 10–30-second session in an isolated test game. Have the trusted native host reserve resources and snapshot game process, game-state source, playback session and OBS recording identity. Do not auto-publish.
2. Run real gameplay with independent key-release enforcement and a pinned source of game-state outcomes. Record the actual OBS output with Star-only isolated speech audio, and observe in/out frame counters over the same interval.
3. Stop and seal the recording first; capture hashes and provenance **outside** the model. Run the media artifact probe, A/V sync analyzer and new cross-lane coherence scorecard. Manual owner review must confirm the footage and heard words match the recorded state.
4. Repeat across game idle/critical moments, speech interruption, low VRAM, stalled input host, OBS render congestion and an intentionally mixed-recording attack. Compare with a no-commentary baseline.
5. Publish a privacy-preserving outcome summary: pass/fail, p50/p95 action/voice timings, observed game reward, frame/encode loss, release failures, memory peaks and sample sizes. Keep source recordings local and opt-in.

### Limitations and no-go claims
This PR implements only the cross-lane consistency layer and tests. It does not run a game, stream, make neural models more intelligent, establish human consciousness, generate speech, capture recordings or provide secure origin attestation. The positive score remains **candidate_for_owner_review** and broadcasts/gameplay remain separately owner-gated.
