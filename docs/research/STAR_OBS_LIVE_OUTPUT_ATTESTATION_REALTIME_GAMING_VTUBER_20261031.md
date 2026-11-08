# STAR — active-output verified streaming, faster gaming intelligence, and expressive VTuber engineering

**Review:** 2026-10-31. **Target:** owner-approved, local-first STAR on Windows, with an 8 GB NVIDIA GPU and optional second research PC. **Evidence class:** repository source review + official vendor documentation + external research; no gameplay, OBS, live voice, hardware benchmark, or production deployment in this change. **Status:** one new enforcement boundary and deterministic synthetic tests; the long-term capabilities below are proposals, not completed implementations.

## 1. The real gap: OBS preview activity is not an active stream

The preceding STAR bridge required a pair of fresh OBS WebSocket `GetStats` windows plus host resource telemetry before recommending background visual work. However, `GetStats` **does not by itself prove the stream output is running**. OBS can continue rendering frames in its preview when broadcasting is stopped. A host collector that trusted these counters and set `StreamTelemetry.live=True` could falsely report a healthy live broadcast.

The OBS WebSocket v5 protocol provides a separate `GetStreamStatus` request with `outputActive` and `outputReconnecting` booleans. STAR now requires a fresh, independently host-verified **active, non-reconnecting stream status** in addition to the existing verified frame-counter and resource evidence. [Protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md); [GetStats source](https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp).

### Implemented contract

- The authorized Windows host obtains `GetStreamStatus.responseData` from its authenticated OBS WebSocket v5 connection and calls `StreamHealthBridge.offer_stream_status(..., host_ms=..., host_verified=True)`. It must do this **before** submitting the frame samples for a newly active stream.
- The bridge retains **only** two validated booleans and a host monotonic timestamp. A missing, stale, replayed, future-dated, malformed, inactive or reconnecting status does not count as an active stream.
- A verified transition from no stream to running, a stop or reconnect clears the existing OBS frame-window baseline and readiness. The collector must observe **two new** ordered `GetStats` samples before STAR can consider the stream healthy again.
- For `telemetry.live=True`, `offer_host` requires both a recent active stream status and one unused, recent OBS frame window. `advise` independently checks status freshness so a status-polling outage revokes prior favorable recommendations.
- `obs_reset` also discards prior output-status evidence. Repeated/unverified status data cannot replace a valid observation. Background work remains **advice-only**, with no new network, OBS, microphone, video, game-input, GPU or process-control privilege.
- Offline `telemetry.live=False` remains supported without an active stream; this is not proof of an active **recording**. An explicit recording-mode status and profile should be added before relying on this policy during offline OBS rehearsal recordings.

**Host integration, in order:**

1. Authenticate OBS WebSocket on loopback; check matching local process/session and `GetStreamStatus` success. Handle `outputReconnecting` separately from output-active.
2. Call `bridge.enable(owner_approved=True)` at an authorized host session boundary; call `bridge.offer_stream_status` as output state is polled.
3. Poll `GetStats` twice with the same monotonic host clock and distinct 250–1000 ms capture intervals. Submit only the four numeric counters via `offer_obs`.
4. Submit verified game/voice/VRAM metrics via `offer_host`. Use `advise` only as a recommendation to the host's independent scheduler, **never** as permission to run work.
5. On OBS reconnect, process replacement, stream toggle, sleep/wake or trust-boundary break, call `obs_reset()` and reacquire status and counter baselines.

**Failure coverage:** `tests/test_stream_health_bridge_output_status.py` covers preview-only frame progression, stopped/reconnecting outputs, stale/replayed/forged status, malformed output flags, future timestamps, session resets, and recovery requiring new data. Existing `test_stream_health_bridge.py` fixtures now supply authentic status evidence. All trials are synthetic; real OBS must still be measured. `host_verified=True` is an **API contract**, not a cryptographic proof. A compromised host can lie; signed sensor transport, process binding and host trust remain a separate engineering concern.

## 2. Why this matters for STAR's speed

A faster local model is not an improvement if it steals GPU time from the game/OBS compositor, misses an interruption or sends an action after the game state changed. Optimize the **whole path**, not only tokens/second:

`capture -> perception -> state compression -> policy -> action freshness -> approved input -> authoritative game outcome`

In parallel:

`viewer/owner turn -> verified transcription -> dialogue -> speech chunk -> audio played -> matching avatar lip/face pose`.

**Acceptance measurements** must include action capture-to-host-acknowledgment p50/p95/p99, game 1% low FPS and frame time, OBS *render* and *output* skipped frames, stream reconnections/drops (from separate output-status metrics), speech first-audio and interruption stop latency, VRAM and RAM headroom, plus objective game win/progress rates. A 10% speed increase is unacceptable if it meaningfully worsens success, stream continuity, or privacy. Test on the same hardware, models, games, prompts, temperatures and seeds; include both live and idle cases.

OBS explicitly recommends leaving GPU capacity for the compositor (for example by capping game FPS) rather than running the game uncapped at maximum load. [Official OBS encoding-performance guide](https://obsproject.com/kb/encoding-performance-troubleshooting/). Therefore, before porting Python components to Rust, benchmark the GPU schedule and cost of vision capture/encoding, TTS and inference first. Rust may help at hot synchronization/serialization loops but cannot solve a GPU-bound render queue by itself.

The official [llama.cpp SPEED-Bench client](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures decode throughput, request latency, and speculative draft acceptance by category. Recommended owner-controlled experiments:

- Fix one model, quantization, context, batch settings and test prompts; compare baseline to `ngram-mod` and to a small draft-model speculative path using the *same* tasks. Test both single-slot and concurrent voice/reasoning loads.
- Explicitly track VRAM reserves for OBS, game textures, avatar rendering and TTS. If speculative draft storage or KV cache displaces these, prefer CPU or short-context workloads, or defer them to the second PC.
- Benchmark prompt-prefix reuse only with separate isolation checks. Shared caches and prompt prefixes must not leak unrelated private conversation context across streams, tool calls, or users.
- Prefer a **fast, bounded game policy** during active gameplay and a stronger background teacher only while not streaming (or on a separate machine).

No unmeasured tokens/second speedup or quality benefit is claimed.

## 3. A learning gamer instead of a one-shot prompt

[RealtimeBench/TORSI, published 2026-10-14](https://arxiv.org/abs/2610.20665), evaluates 180 continuously running game tasks and proposes a slower teacher that studies failure cases between attempts and distills tested lessons into a faster live-playing student. Its reported 13.51 -> 24.19 improvement is **the authors' result**, not STAR's.

For STAR, implement the following **gated, measurable chain** instead of letting an LLM overwrite its own gameplay policy directly:

1. Observe from the approved game host: timestamps, visible state, player-local controls, objective progress and whether a past action actually landed. No anti-cheat bypasses, unauthorized online automation or fabricated outcomes.
2. A quick action-selection policy produces a short-horizon plan; each action is validated by existing action-freshness, input allowlist and session boundaries. No hidden long reasoning in a real-time control loop.
3. Between rounds, a stronger teacher reads owner-consented, privacy-filtered session traces, identifies failure categories (late response, bad control timing, missing UI cue, incorrect goal prediction), and proposes a **small** strategy revision.
4. Star Core Forge stores the candidate strategy and its training evidence with a versioned rollback path. Run preregistered baseline/candidate trials using matched unseen seeds, distinct game scenarios and actual game-state outcomes. Evaluate local regressions and worst-case latency as well as overall wins.
5. Promote only after independent holdout evidence and the host's review requirements; monitor for regression and roll back automatically when the authorized deployment policy permits. Keep the teacher away from sealed test labels.

Future skills to evaluate: camera navigation, inventory/gear selection, platforming timing, interacting with menus, reacting to hazards, team play, learning after an unfamiliar mechanic is introduced, and describing *what just occurred* without hallucinating an achievement. Generalize across permitted games rather than memorizing UI pixels.

## 4. VTuber behavior that feels natural without pretending to be a human

STAR can have a stable persona, preferences, jokes, hesitations, motivations and a playful social history grounded in authentic streams. Humanlike **presentation** means good latency, turn-taking and emotional timing—not misleading people that a biological person is behind the avatar.

Implement an audio-first, interruption-aware conversation layer: speech generation can yield short chunks, owner-confirmed barge-in cancels both audio playback and stale avatar gestures, viewer speech may hold future responses, and STAR stops talking during high-focus gameplay. Use a shared monotonic timeline to coordinate eye gaze, phoneme/viseme lips, blinks, posture, hair motion, reactive surprise and laughter. A laugh must be contextually appropriate; a silent moment is sometimes a better response than another generated sentence. No always-listening microphone or viewer identity store without authorization.

**Speech research candidates:** [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) documents CPU-capable streaming speech and small English model options released in October 2026. [VoXtream](https://herimor.github.io/voxtream/) examines low-latency audio generation from incremental text, and [VoiceChat-TTS (2026-08-13)](https://arxiv.org/abs/2608.13831) studies continuous, interruptible TTS. None is currently installed or performance-validated in STAR by this update. Evaluation must measure intelligibility, pronunciation, warmth and expressive range, interruptions, and first-audible-chunk delay on the *actual* gaming PC. Voice cloning requires permission from the speaker.

**Memory and identity:** Store only genuinely observed gameplay events with game/session provenance, brief generated stream recaps, explicit fictional character lore and separate sourced factual knowledge. Attach an uncertainty or evidence tag. Let STAR refer back to an actual win or funny incident; never invent a real childhood, private relationship, human identity or a viewer interaction that never happened.

## 5. Roblox/game creation and world-quality intelligence

[Roblox OpenGameEval (paper 2026-10-01)](https://github.com/Roblox/open-game-eval) evaluates 84 curated Studio tasks with executable scene and play-session checks. Its authors report that inspecting relevant objects before editing correlates with better task completion. STAR should treat **inspect -> design -> build -> simulate -> inspect again -> repair -> compare to spec** as mandatory for difficult scenes.

Extend Star Core Forge to collect independent *structural and visual* evidence: anchored walls, coherent room adjacency, nonintersecting props, correct player scale and collision, aligned material UVs, sensible light falloff, avatar rig proportions, readable UI safe areas, animation/hand attachment verification, network authority and multiplayer synchronization. Verify at multiple camera distances and graphics quality levels. Use UI screenshots or local scene renders as visual evidence; a working script alone cannot prove the game looks polished.

Benchmark completed mini-games and unfamiliar game tasks, not only source-code syntax. Enforce novel ideas by scoring gameplay differentiation separately from correctness. Preserve licensing/source attribution for retrieved models, audio, sprites, textures and code. New features remain opt-in by default.

## 6. General knowledge and local-first reasoning

The objective is **calibrated usefulness**, not dumping huge unverified text into a context window. Maintain a knowledge ledger with (source, retrieval date, version, scope, confidence, license, provenance, and whether safe to quote publicly). Route lightweight recurring questions to fast retrieval; use a stronger verifier for ambiguous, novel, multimodal or high-stakes prompts. Evaluate with unseen factual, reasoning and coding tasks, citation correctness, contradiction detection, memory isolation, and latency measured under streaming load.

The best next integration is an **authorized OBS output-status and game/voice hardware rehearsal** rather than another unmeasured architectural rewrite. Record baseline vs candidate in 10-minute repeated local sessions, collect anonymous resource/performance statistics and genuine outcomes, and publish a reproducible acceptance report. Keep user approval for high-risk external operations, while letting routine permitted local experiments run autonomously after host setup.

### Definition of done for this patch

- [x] Production live-admission policy requires recent independently attested active, non-reconnecting OBS output.
- [x] Status change, invalid evidence and OBS reset invalidate previous readiness; replay/future/stale output evidence fails closed.
- [x] Synthetic regression tests added and existing fixtures adapted.
- [ ] GitHub Python/Pyright/React CI green on final head.
- [ ] Authenticated Windows host feeds real OBS GetStreamStatus and GetStats to bridge.
- [ ] Live and recording-mode distinction validated on host.
- [ ] Repeatable before/after gameplay FPS, OBS, voice, vision, inference and memory-isolation benchmark completed.
