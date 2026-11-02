# Star AI — OBS epoch continuity, two-timescale gaming intelligence and VTuber performance
**Research / engineering note:** 2026-11-02. **Status:** deterministic, opt-in advisory-layer improvement in this branch; the host integration and real-streaming gains described below are *not* implemented or measured.

## 1. Reproduced threat: returning to the same OBS state is NOT continuity

Prior change #915 records the independent OBS boolean when a game-inference lease is offered and checks it again when the model finishes. It correctly rejects OFF→ON and ON→OFF, but cannot notice **OFF→ON→OFF** or **ON→OFF→ON** between those checks.

The game engine can keep producing valid frames throughout this transition. However, the model's original inference workload, consent regime and output constraints are not necessarily valid after a broadcast starts or stops. A stale model action should never qualify merely because the last OBS boolean equals the initial one.

### Code implemented in this branch

- Adds optional `stream_epoch: int | None` to `RealtimeGameLoop.offer`, `finish`, and `claim`. All are **trusted-desktop-host-only** inputs, not model output or game telemetry. The epoch must be an integer in `[0, 2^63-1]` (not a bool), increasing on every OBS state change, including transient starts/stops.
- Freezes the offer-time epoch in the identity-bound `GameThinkLease`. Epoch changes during inference reject the consumed lease with `stream_epoch_changed_during_inference`, even if the OBS boolean is the same on both sides.
- Once used in an episode, epoch evidence cannot be removed or reversed on later offers. A missing finish-time epoch invalidates an epoch-protected lease. Introducing a finish-time epoch that was absent from the offer also invalidates the lease.
- Binds the completed permit to the same epoch at the final `claim` gate, *after* inference but before the trusted adapter dispatches input. Missing/changed evidence revokes the gate instead of merely delaying input, so the old permit cannot be resurrected by presenting the previous epoch.
- Preserves the legacy behavior when no epoch is used, for backward compatibility; this mode **does not solve ABA**. This is only a safety gate, not an OBS monitor, model improvement, key injector or permission to stream. The remaining input adapter must independently verify OBS/focus/owner consent at the moment of physical input dispatch.
- No new default-on features. No OBS, model, game, microphone, graphics engine or network calls occur in the implemented module or its tests.

### Host integration that is still required

The host must operate a **single continuously authenticated local OBS WebSocket 5** output-event subscriber, tracking `StreamStateChanged`, reconnect and OBS restart over an intact event stream and independently fencing with `GetStreamStatus`. Do not infer an epoch from two polled booleans, event timestamps, screen pixels, a model's statement, or reconnecting to a fresh socket after losing events. An opaque process-ID/connection-generation stamp is needed to bind every reading to one authenticated OBS process; disconnect, lag, missed events, counter overflow or process restart invalidates the current live episode rather than silently resetting the count. The existing `star/obs_stream_event_witness.py` supplies a starting point for same-socket event fences in a separate host but is currently specialized for active-stream benchmarking, not this gameplay loop.

The trusted host must attest the epoch **immediately before** offer, completion and the final key dispatch; the current code only compares the supplied numbers. For full end-to-end safety, the actual host key adapter must carry the proof through dispatch. No number or boolean can itself prove that OBS events were captured reliably.

### Tests and real-world acceptance

Deterministic simulated cases cover state-only start/stop, both ABA directions, unchanged epoch, missing/reversed/invalid epochs, lease replay, sticky evidence within a session, missing/changed claim-time epoch, and final one-shot claim. Actual Windows tests must additionally simulate socket disconnect, process replacement, event-flood, stream reconnect, key-release and final dispatch races; these have **not** been run.

Success = no permitted input on an ABA transition; zero unauthorized key-downs; no worker admitted after a revoked epoch; no regression in stable, host-attested scenes; no unexpected stream start or external connection from the test process.

## 2. Intelligence under a live clock: choose meaningful work, not maximum model size

**Evidence (2026-10-14):** *The World Won't Wait* introduces RealtimeBench (180 tasks, six game types) and TORSI: a fast in-game student paired with a slow offline teacher that learns from unsuccessful attempts. The paper reports student progress moving from 13.51 to 24.19 out of 100 after two rounds. This is **not** a Star result. Source: https://arxiv.org/abs/2610.20665 .

**Architecture to test:** isolate a low-latency `observe→choose→act` student from a resource-limited teacher that runs when gameplay is paused or completed. The student sees a compact, verified, temporally tagged state (game ID/version, visible HUD and hazard cues, allowed action IDs, last action outcome, uncertainty, monotonic clock and deadline). Avoid giving it the entire chat transcript, all world history and unrestricted external tools on each frame. The teacher can examine replays off-stream, explain failed strategies, generate bounded candidate skills and submit them to an independent verifier.

**Verified learning gate:** for each skill, record immutable scenario version + held-out seeds + before/after paired outcomes, execution latency, failure cases, negative transfer and uncertainty. Require independent scenario diversity; hash-based duplicate suppression alone does not prove independence. Reject gains that disappear on held-out games or cause new action-safety regressions. Store approved skills locally with provenance and rollback (GitHub is an export/review surface, not a mandatory runtime dependency).

**Evidence (2026-05-29):** AgentOdyssey evaluates long-horizon text-game agents for world knowledge, episodic memory, exploration, action diversity and cost. Short-term memory improves multiple paradigms, but overall performance remains far from humans. Source: https://arxiv.org/abs/2606.24893 .

**Additional experiments:** procedural difficulty ladders, variable frame rate, partial HUD visibility, unseen boss patterns, delayed rewards, and controller errors. Track progress gained *per second of real wall clock*, failure recovery time, successes per dollar/watt and late-action rate. Every skill promotes only after repeated independent trials.

## 3. 8 GB VRAM inference: measure contention, avoid blind speculative acceleration

Do **not** assume a 9B model, enormous context window or speculative decoding is always fast on 8 GB VRAM. Model weights, KV cache, image/vision encoders, TTS, game textures, compositor and OBS compete for physical memory.

Suggested 4-arm *opt-in* inference benchmark on identical executable tasks:
A. current known-good setup; B. stable-prefix KV caching; C. modest speculative draft; D. reduced context/quantized KV or smaller fast model. Hold target output quality and completion validity constant; compare p50/p95 first-token and *complete correct response* latency, tokens/sec, GPU memory, game FPS p1/p5, OBS dropped/rendering frames, speech backlog, and per-request cancellation rate. Require nonbroadcast game+avatar+OBS rehearsal rather than idle-only results.

**2026-10-09 concrete regression to watch:** llama.cpp issue #30252 documents prompt cache idle-slot saves stalling other requests for multiple seconds on some configurations. Record the exact llama.cpp commit, flags, batch/parallel slots and cache state; abort if enabling cache makes p95 latency worse. https://github.com/ggml-org/llama.cpp/issues/30252 .

**SPEED-Bench** explicitly measures spec-decode latency, throughput and draft acceptance. It is a baseline tool, not proof of universal speedup. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .

**Task routing:** low-compute policy/rules engine handles trivial chat acknowledgement, static states and known mechanics; a small quick model handles time-critical dialogue/game decisions; a stronger, slower model handles design/debugging outside the live loop. If pressure rises: drop low-priority vision samples first, delay background training/research, preserve key-up and audible-speech synchronization, and skip uncertain or overdue game actions. Runtime scheduler must never trigger self-modification while broadcasting.

## 4. Humanlike *performance*, not fabricated human identity

**2026-03-03:** Proact-VL separates deciding *when* to speak from *what* to say in live-game solo commentary, co-commentary and guidance settings. Build a lightweight `speak | backchannel | defer | silence` policy grounded in verified events. Reward useful reactions and listener comfort, not constant chatter. https://arxiv.org/abs/2603.03447 .

**2026-10-15:** VoxTurn (0.8B) combines end-of-turn, continuation and backchannel decisions; its paper reports 11.5% English false cut-offs at a 300ms latency budget in its evaluation, not Star's. Compare it to Star's existing endpointing gate under actual viewer pauses instead of adopting automatically. https://arxiv.org/abs/2610.21150 .

**2026-08-13:** VoiceChat-TTS studies continuous text-driven speech with explicit interruption and silence support, a potential reference for natural interruption behavior. Evaluate licenses, CPU/GPU cost and actual output quality before integration. https://arxiv.org/abs/2608.13831 .

**2026-10-20/21:** Kyutai Pocket TTS released small English families (18m, 7m, 2m); release v4.0.1 fixed some incorrect pronunciations. Test CPU models with word error, first audible PCM time, perceived emotion and GPU contention. Don't confuse published 25× real-time synthesis claims with the machine's end-to-end first-audio latency. https://github.com/kyutai-labs/pocket-tts/releases .

**VTube Studio** supports approved plugin hotkeys, custom tracking-parameter injection, face and model control. Couple head nods, blink timing, expression and mouth movement to the *actual output-device playback clock*, not text-generation time. https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins .

Humanlike character behaviors to add via reversible, owner-controlled preferences: lightweight autobiographical memories from true episodes; consistent game tastes and running jokes; reacting to wins/losses without claiming experiences she did not have; nuanced listening with brief acknowledgements; energy recovery and deliberate silence; safe responses to unsolicited viewer messages; playful Star/Astro/Amber interactions. Clearly identify Star as an AI VTuber; never pretend to be a real human or send private account information to viewers.

Metrics: interruption false-positive rate, unnecessary-commentary rate, repeated-commentary rate, latency to audible reaction from a verified game event, speech/viseme drift, authentic memory recall accuracy, viewer turn fairness and hours without frozen or desynchronized avatar controls. Test on recordings before any real live broadcast.

## 5. Game creation and general knowledge: inspect, build, run, repair

**Roblox OpenGameEval (2026-10-01)** evaluates 84 stateful Roblox Studio tasks with executable scene/play checks. The paper reports better success when agents inspect objects they touch before editing. Use the inspect-first architecture and reproducible Studio runner as evaluation guidance, not as a claim of Star already passing. https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval .

Proposed skill harness: (1) inventory current place hierarchy/assets, scripts, plugin settings and API version; (2) generate 4 candidate Luau changes in isolated branches/sessions; (3) lint and analyze with StyLua/Selene/luau-analyze; (4) run headless/static tests and real Studio Lab play tests; (5) independently inspect render screenshots, geometry collisions, HUD safe areas, network authority and multiplayer behavior; (6) pick the fastest correct passing solution; (7) store the verified lesson with an expiry/API provenance marker and rollback. Require human review for public publishing, game purchases, real user chats and other external side effects.

General-knowledge system: start with curated official references, retrieval with document/version/date citation, answer confidence calibration, a contradiction checker, and separable verified factual memories. Add text, speech, images, video, coding, animation and Blender modules behind resource-aware plugins, **disabled by default**. Test retrieval freshness and prompt-injection resilience: downloaded pages and viewer chat must never supply agent policy, OBS credentials, stream keys or tool authorization.

## 6. Prioritization and honest status

**Implemented here:** host-optional epoch parameter, identity-bound lease/permit checks, zero-OBS/zero-input deterministic regression tests. The system is backward compatible and **not yet connected to a live event-counting host**.

**Next highest-value dependencies, in order:** trusted monotonic OBS event epoch producer + final Windows key-dispatch binding; one end-to-end **nonbroadcast** Windows game/OBS/voice/avatar rehearsal; on-hardware latency A/B; supervised autonomous practice against held-out scenarios; voice/prosody and socially aware commentary evaluation; actual Studio Lab inspect/build/test/repair harness.

**Do not report as achieved:** model training, real-game win improvements, generalized intelligence improvements, streaming personality quality, true human consciousness, real GPU throughput speedups, or a completed Windows VTuber test. Those require independent real measurements and owner-controlled rollout.
