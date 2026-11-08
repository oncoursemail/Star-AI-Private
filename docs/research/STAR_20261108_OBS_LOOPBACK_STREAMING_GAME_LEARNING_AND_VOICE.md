# STAR — real local OBS transport, playable intelligence and natural VTuber research

**Date:** November 8, 2026. **Status:** draft, locally tested, Windows live device NOT yet exercised. **Scope:** opt-in observation, not streaming authorization.

## Implementation: bridge the previous host integration gap

PR #1077 had a carefully verified **pure data** pipeline but no trusted transport to OBS. New `star/obs_live_local_host.py` adds `ObsLoopbackLiveHost` as a bounded host-owned connector.

- Before opening a socket, the owner must opt in and select the actual OBS PID and OS process birth timestamp. A fresh Windows OS process snapshot must confirm the same PID, birth timestamp and OBS executable name. The identity is checked again after handshake, before each sample and afterward. A PID reused by another process is not accepted.
- Connects only to `ws://127.0.0.1:<bounded port>` via existing local no-proxy `_local_connection`. Uses OBS v5 authentication challenge and only the `obswebsocket.json` protocol. It never sends the password to the socket, command line, output, log or model.
- Subscribes to the OBS **Outputs** category (event bit `1 << 6`). Sends **only** `GetStats` and `GetStreamStatus`; a real OBS state-change event, stray/unrecognized op, broken request correlation, unsuccessful read or socket failure immediately invalidates the live load epoch. No stream/record/scene/volume/transition input or other state changes are requested.
- Timestamps both validated responses from a single host monotonic clock. Requires a **real independently collected** `HostLoadReceipt` from a trusted host callback for game p95 presentation time, GPU VRAM and first-audible speech latency. Missing sensor values produce *unavailable*, never fake zero or green. The previous `ObsLiveLoadPipeline` enforces alignment, interval progression, quantitative agreement and governor warmup.
- Password, process name/PID, raw protocol messages, viewer text and captured media never enter reported metrics. Stopping or any error revokes the workload governor's earlier success. The resulting recommendation is advisory, never permission to speak, play, start OBS, record or go live.

**Known boundaries:** OBS's authenticated socket is not cryptographic proof of a sensor callback. The host OS process snapshot is genuine only if the application has not exposed its process reader to an untrusted model. Receipt callbacks must originate with native host code, not chat or a synthesized mock. The output-event subscription provides continuity only while the socket survives; a missed event or socket reset must trigger another full owner-armed epoch. There is no claim that being connected proves an actual OBS broadcast is consented to. No live broadcast or Windows PC operation was attempted in this change. OBS cannot be privately stress-tested for live network-loss metrics without an owner-approved actual live stream; use OBS recording-specific witnesses for nonbroadcast rehearsal instead.

## Priority 1 — real host sensor and private benchmark

The direct OBS transport is now present as **opt-in library code**. To evaluate it on a real machine without exposing a stream key:

1. Bind the host callback to **actual** Windows process identity plus NVIDIA WDDM/driver GPU counters, native game frame-time instrumentation and physical first-audible PCM timestamps. If any are absent, stop the pipeline. Keep the sensor callback unavailable until it is truly implemented.
2. For normal **nonbroadcast** rehearsals, use Star's separate local OBS private-recording monitor, do not fake `GetStreamStatus.outputActive`. Collect gameplay frame-time p50/p95/1%-low proxy, OBS render and encoder missed percentage, GPU/VRAM peaks, model TTFT/p95, voice first-audible onset and interruption-to-silence, actual lip-sync error and game task success.
3. Test at least 5 repeated paired randomized A/B sessions on the same game scenes: commentary governor OFF/ON, same prompts/seeds/models, equivalent local capture and process load. Plot both median and worst-tail behavior; no speed claim without a measured delta. Hard gates: no unapproved broadcast, no unapproved game input, no playback despite a revoked epoch, zero fabricated host receipts.
4. If an owner separately approves a private/unlisted live-stream test, measure OBS WebSocket output-network loss and reconcile with OBS log. A local OBS connection by itself is never permission for that experiment.

## Priority 2 — game agent that improves its *win rate*, not its prose

**Gym-Anything-RT (October 27, 2026)** generated 100 real-time minigames and reports large real-time versus paused performance gaps. Therefore combine a deterministic deadline-bounded reaction path with slow between-round strategy and offline practice. Do not route 30Hz input through an expensive long-thinking model. Candidate action commands require fresh verified gameplay frames, game focus, policy permissions, and an independent action-outcome acknowledgment.

**Gym-Anything for Robotics (October 29, 2026)** shows an instructive *training* pattern: use privileged simulator state to help an agent during practice, but evaluate generalization with distinct test tasks without privileged help. Apply this to Star's Roblox Studio lab: create procedural mini-games, expose Studio server state **only to the training teacher**, compile/format/lint Luau, play by screen observations on unknown maps, receive tool-controlled outcome receipts, repair failures, and seal holdout maps/seeds away from the learner. Treat suspicious evidence and unverified wins as failure.

**Proposed gate, not a result:** 3 game families; 20 training and 20 sealed holdout levels each, at least 10 independent attempts per configuration with the same reaction deadline and compute limit. Compare reflex-only, teacher-only and teacher+reflex; report held-out win rate, uncertainty interval, latency p50/p95, late/skipped action ratio, intervention count, and input focus violations. Only verified holdout improvement earns a reusable capability.

## Priority 3 — faster intelligence on Star's actual 8GB GPU

Do NOT optimize tokens/second while losing game FPS. Benchmark `llama.cpp` CPU/GPU layer placement, KV caching, compact model routing, vision resolution choices, quantized draft-assisted speculative decoding and CPU TTS vs GPU TTS at 4K, 8K and 16K context lengths. Record VRAM and system RAM peak, prompt/decode throughput, TTFT, warm/cold caches, task correctness, gameplay 1% lows, OBS render losses and audible response p95. Only enable proven net wins with automatic resource rollback.

For *general knowledge*, use per-subject verified, versioned retrieval with source/date/provenance and explicit unknown state. Keep tentative reasoning, true experiences, fictional persona lore, untrusted web text and signed game outcomes separate. Reward factual accuracy, not confidence. A self-training agent must not rewrite its own holdouts or sign its own success.

## Priority 4 — expressive, natural, socially engaging VTubing

**Proact-VL (ICML 2026)** studied when to speak, *how much* to say, and commentary vs co-commentary vs user guidance. Star should use event-based speech admission, comfortable silence, attention to viewer intent and game danger, interrupted turn cleanup, novelty pacing and optional spontaneous humor. Count factual errors, interruptions respected, overtalk, silent opportunities, viewer-turn acknowledgment latency and self-correction quality; never optimize solely for uninterrupted talking.

**VoiceChat-TTS (August 13, 2026)** proposes continuous low-latency streamable synthesis driven by text-token streams, barge-in control tokens and silence without resetting its cache. This is a *benchmark candidate*, not a verified local Windows model replacement. Evaluate against existing Star speech with identical samples and concurrency: time-to-first-audible PCM, interrupt-to-physical-quiet, MOS/ABX naturalness and CPU/VRAM conflict. Playback state must come from native audio output callbacks, not generated words.

Sync expressive face and eyes to **audibly played** PCM and actual game events; if audio is canceled, neutralize the avatar rather than animate unspoken words. Keep Star's consistent interests, memory and emotions as transparent expressive AI persona, not assertions of biological human identity or unverified real relationships.

## Primary dated references (verified November 8, 2026)

- Official OBS WebSocket v5 protocol / authentication, operations and `EventSubscription::Outputs`: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- Aggarwal & Welleck, Gym-Anything-RT, **October 27, 2026**: https://arxiv.org/abs/2610.37567
- Aggarwal & Welleck, Gym-Anything for Robotics, **October 29, 2026**: https://arxiv.org/abs/2610.40565
- Yan et al., Proact-VL, **ICML 2026**: https://proceedings.mlr.press/v306/yan26c.html
- Casanova et al., VoiceChat-TTS, **August 13, 2026**: https://arxiv.org/abs/2608.13831
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Roblox Studio MCP Open Cloud and assets **November 4–5, 2026**: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

## Release status

All newly added code is default-off, host-only and no real OBS/network/session was opened in automated verification. Deterministic mocks verify logic boundaries, not the integrity of a real physical machine. Leave this PR as a draft until actual Windows host receipt plumbing and private nonbroadcast quality/performance tests pass. No speed, gameplay skill, human-likeness or full streamer deployment gains are claimed yet.
