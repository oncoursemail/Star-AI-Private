# STAR: stricter snapshot freshness and pre-dispatch latency attribution
**Research and engineering date: October 31, 2026**  
**Status:** Python code, regression tests and engineering notes on draft PR #845; no live game, OBS, hardware speed benchmark or inference model change.

## Audited defect and scope
STAR has two host-mediated *advisory* checks, not a keypress driver. The earlier game-action gate rejects frames whose capture timestamps do not strictly increase. Its supplementary GameActionFreshnessGate previously allowed a higher sequence number reusing the **same captured timestamp**. In an asynchronous perception pipeline, a delayed or duplicated frame can be relabeled with a newer queue sequence even though the game scene did not advance.

The corrected freshness gate rejects non-increasing observation timestamps. It deliberately checks stale age first, preserving established stale-denial semantics when a frame exceeds the configured budget. A rejected duplicate does not consume an allowed sequence slot. No remote game is controlled; a trusted host still must verify game permission, process focus, key release, input policy and monotonic clock provenance.

## Implemented bounded speed diagnostics
Until this change, the freshness gate returned a yes/no decision and counters, making it hard to separate model latency from waiting in the input queue. It now retains the latest **64 accepted** observations as anonymous numeric summaries, with nearest-rank p50/p95 for three timings:

- **Capture-to-decision:** host-reported perception and model decision time.
- **Decision-to-assessment:** delay between model decision and freshness-gate check, including potential queue/transport waiting.
- **Capture-to-assessment:** complete age of the observed game scene at the pre-dispatch check.

Unverified, stale, wrong-session, reversed-clock and replayed observations do not enter these samples. The measurements contain no screenshot, input payload, player identity, game identifier, chat, prompt or audio. The samples reset on disable and when a new approved session starts. A successful freshness check **does not** mean an OS input was sent, an action was performed, or Star won a game. Future trusted host instrumentation must record the physical dispatch stage separately.

## Research implications for intelligence and game mastery
**Thinking under a live game clock:** The October 14, 2026 *RealtimeBench* paper (180 tasks, six continuously running game types) demonstrates the gap between paused and real-time performance. Its TORSI approach uses an offline teacher to improve a fast student between sessions. Recommended STAR adaptation: keep a small, bounded action student in the live loop, have the deeper reasoning teacher analyze verified mistakes after episodes, then promote only independently tested improvements. Paper: https://arxiv.org/abs/2610.20665

**Find the real latency bottleneck first:** High capture-to-decision p95 indicates perceptual inference or skill lookup needs attention. High decision-to-assessment p95 indicates scheduling/queue/transport pressure. A good result in both stages does not establish low host dispatch latency. Candidate fixes: latest-only vision queues, frame deduplication, preloaded approved skill cards, avoid off-path background work on the gaming GPU, and short plans that fit the observation deadline. Run same seeds/maps for baseline and candidate and retain independent win/progress evaluation.

**Model-server testing:** Official llama.cpp SPEED-Bench measures throughput, end-to-end request latency and speculative draft acceptance with reproducible client configurations. Compare prefill and decode separately with identical model weights, quantization, context, task mix and concurrency; pair those numbers with game 1% low FPS and audible first-sample timing before claiming speed improvements. The tool does not start the server automatically. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## Research implications for humanlike VTuber behavior
Conversation should be paced around actual game urgency, not around maximum speech rate. Natural pauses and quick context-aware reactions matter. Use host-confirmed audio playback to trigger mouth movement, gaze and ear/twin-tail gestures rather than animating at text generation time. Use the privacy-preserving episode journal only for consented, attested actual gameplay memories, and keep Star clearly identified as an AI instead of inventing a real human biography.

Pocket TTS released smaller English CPU-oriented models on October 20, 2026, followed by a relevant small-model correction in v4.0.1 on October 21. Evaluate 18M/7M/experimental 2M model candidates against Star's current voice for onset latency, naturalness, pronunciation, CPU burden and voice consistency. Do not replace production speech without a blinded listening test and a rollback path. Source: https://github.com/kyutai-labs/pocket-tts/releases

LiveKit documents a local CPU **v1-mini** audio turn detector. Pin that version explicitly if evaluated offline, rather than silently selecting a cloud-dependent model. It detects end-of-turn probability; it is not speaker authentication or proof of humanlike quality. Source: https://docs.livekit.io/agents/logic/turns/turn-detector/

## Game building and general knowledge
Roblox StudioTestService can automate multiplayer scenarios, which is useful for validating complete Roblox projects. Acceptance should require coherent geometry/anchors, no missing parts or texture clipping, camera/mobile UI checks, animation and physics, functional goals, server/client events, joining/leaving and controlled load tests—not just passing Luau syntax. For general knowledge, separate verified source-backed facts, test receipts, speculative hypotheses, and character fiction; evaluate unseen math, physics, Blender, writing, UI, programming, visual reasoning and game mechanics tasks before promoting new knowledge as reliable. Official Studio API: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## Reproducible Windows acceptance and rollback
Record an owner-authorized, private gaming + OBS rehearsal and run 30 matched unseen scenarios with fixed model/server/hardware configurations. Compare p50/p95 of capture-to-decision, decision-to-assessment, capture-to-physical-input and first audible playback; also report game FPS 1% lows, VRAM peak, key release safety, verified wins, repeated-chat/reaction rates, voice rating, avatar sync and unsupported memory claims. Roll back if any candidate increases wrong inputs, permission failures, low-FPS events, latency, or off-topic speech even if tokens/sec improves.

**Validation:** run the focused freshness/action-gate tests and full offline Python, React and Pyright CI. Synthetic green checks are not hardware evidence. Keep draft PR unmerged. The repo named Star-AI-Private currently has public GitHub visibility; never store credentials or private streaming recordings here.