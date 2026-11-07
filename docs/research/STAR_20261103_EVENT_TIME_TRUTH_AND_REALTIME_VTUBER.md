# STAR — Truthful real-time game events and faster, more natural VTuber behavior

**Research and implementation note — November 3, 2026.** Status: tested Python changes in a draft branch; not an on-air deployment, model training run, game-winning benchmark, or measured inference acceleration.

## Newly reproduced failure: game event time is not delivery time

The host already verifies PRACTICE signatures, rejects duplicate capture hashes and enforces a short age limit. But network buffering, sensor queues or simultaneous callbacks can deliver **different signed game observations out of order**. The prior streamer reaction logic computed a failure streak and a comeback using **arrival order**, not the host-signed observation timestamp. A success that occurred *before* three failures could be delivered afterward, clear the failure streak and be mistaken for a comeback; later genuine recovery then lost its moment. Separate signed evidence makes this distinct from the duplicate-capture bug fixed in PR #931.

This patch introduces a per-curated-action, per-episode watermark in VerifiedGameReactionHost. A fresh signed observation whose Unix-second timestamp is not *strictly newer* than the most recently narrated/processed fresh observation for that action is accepted into the verified **historical** episode, but cannot alter the live failure streak or queue speech. Exact-second ties are ambiguous without a trusted sequence/monotonic game-clock receipt: fail closed for immediate narrative. This does not reject evidence from skill learning, and separate action IDs do not block one another. Watermarks reset on shutdown and fresh enable. Exposed diagnostics are numeric counts only, not trial identifiers, timestamps, hashes, transcripts or player details.

**Threat model:** helps against delayed, reordered but correctly signed observations. Does not establish capture authenticity beyond the signer, prove event ordering within one second, prevent a malicious signer from forging timestamps, authenticate PC input or guarantee speaker playback. A host-level strictly monotonic game-world event counter plus captured/accepted receipts is the preferred future primitive.

**Reproduction:** three adversarial tests failed against the unpatched host (late success wrongly returned cooldown; late failures counted toward a three-failure streak; an equal-second success was queued as fresh). They pass with the event-time fence. Existing StreamEpisode verification, consent and short event freshness continue unchanged.

## What to build next: highly capable real-time gaming AI

**Evidence:** *The World Won't Wait* / RealtimeBench, first posted October 14, 2026, tests 180 tasks across six live-clock game types. Its reported two-timescale offline learning improvements are *not* STAR results: https://arxiv.org/abs/2610.20665

1. **Immediate game lane:** small latency-bounded action model with explicit no-op, hard deadlines, foveated frame changes, tool schemas, emergency-stop path and game-side action acknowledgements. During high-threat moments, prioritize the game and do not generate spontaneous speech.
2. **Slow teaching lane:** use richer reasoning between attempts to explain failures, compare strategies, write compact transferable skill cards, and propose harder practice scenarios. Separate practice captures from holdout seeds and maps; independently grade *live-clock objective progress*, not stylistic explanations. Retain rollback and baseline.
3. **Observation provenance:** attach trusted per-game tick/sequence, capture monotonic timestamp, deadline, action proposal timestamp, physical input receipt and observed effect. Reject stale/out-of-order facts from live narration; do not discard valid historical learning evidence. Check game resets, paused-state transitions and timebase discontinuities.
4. **General knowledge:** maintain provenance-tagged, timestamped local retrieval over documentation and approved lessons; expose contradictions/uncertainty instead of inventing facts. Never let game chat, screen text or tool output grant permissions.
5. **Roblox builder:** apply inspect-before-edit, best-of-N code solutions, Luau formatting/static analysis, reversible Studio diffs, automated multiplayer/playability tests and image/video comparison. Roblox OpenGameEval (released October 1, 2026) scores stateful engine changes plus play sessions; it reports substantial room for improvement: https://github.com/Roblox/open-game-eval ; https://arxiv.org/abs/2610.02563

## Stream naturalness without fictional human identity

**Evidence:** Microsoft's Proact-VL (ICML 2026, May) evaluates proactive gaming companion commentary and guidance, including whether/when to speak: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

- Maintain a deliberate-speaking policy: silent by default, interruptible by real owner input, trigger on viewer questions, important game events and natural moments between intense game actions. Dedupe chat questions and never announce unobserved wins or fabricated personal memories.
- Build expressive natural dialogue through verified memories, stable preferences, conversation repair, varying prosody and lip/eye/hair animation driven by *actual playout* audio samples. Star, Astro and Amber are characters, not proof of human participants. Disclose clearly that Star is AI.
- Track a **speech consequence budget** per scene: owner interruption latency, spurious noise interruptions, first audible PCM delay, viewer overlap, silence during clutch moments, old-event commentary, game FPS and OBS dropped frames. Grade complete playback, not text-generation tokens alone.
- LiveKit turn detection and adaptive interruption strategies are reference implementations, not installed capabilities. Check actual pinned SDK APIs before integration: https://docs.livekit.io/agents/logic/turns/ ; https://livekit.com/blog/turn-detection-and-interruption-handling
- Kyutai Pocket TTS offers CPU-capable streaming speech with October 2026 smaller English model variants (18.2M, 6.9M, 1.9M parameters). These *published* speed claims are not measured on STAR's Windows machines. Compare output intelligibility, prosody, CPU contention and first audible chunk latency under game+OBS load: https://github.com/kyutai-labs/pocket-tts

## Performance experiment design for 8 GB-class GPUs

Test identical fixed model weights, model/quantization, prompt samples, context window, batch size, GPU-reservation budget and game scene for each matched pair. Start with a no-speculation llama.cpp baseline; vary prefix caching, reduced context, foveated attention, concurrency and speculative decoding individually. The official SPEED-Bench tool reports prompt/decode throughput, latency and draft acceptance, but a higher decode rate alone does **not** imply improved live-game success: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Readiness matrix:** at least 20 complete paired game/OBS runs per candidate with independent input receipts; p50/p95/p99 decision deadline misses; 1% low game FPS; OBS dropped frames; 95th percentile first-audible delay; owner barge-in stop time; stale commentary/fictional claims; CPU/RAM/VRAM peaks and recovered-failure skill scores. Treat outcomes as *inconclusive* if results are correlated across repeated captures, holdout maps leak into training, runs are paused, or game/world clocks are not continuous. Candidate promotion must be manual and reversible.

**Immediate sequence:** (1) land and review event-time fence tests, (2) implement independent game tick or millisecond capture ordering for same-second events, (3) perform nonbroadcast Windows rehearsal linking input worker/watchdog, host-signed frame receipts, game-world observations, real speech output and avatar/OBS traces, (4) benchmark fast student + slow teacher in small private games, and (5) select voice and model routing based on those real measurements.

No live stream, human-like consciousness, independently learned improvement, or performance gains are claimed by this note.