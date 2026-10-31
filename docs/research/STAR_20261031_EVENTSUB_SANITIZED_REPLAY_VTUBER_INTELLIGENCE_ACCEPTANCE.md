# STAR — Verified Twitch ingress, real-time VTuber intelligence, and performance acceptance
**Date:** 2026-10-31 · **Scope:** source-audited design and code changes on draft branch only; no physical game, Twitch channel, OBS, microphone, neural model or Windows computer controlled.

## Executive result and evidence boundary

This change improves the **last-mile conversational trust boundary** for the opt-in pure `TwitchEventSubIngress` adapter. Before this patch, a host could attest `moderated=True` yet the adapter still forwarded the **original raw** `event.message.text`; if an independent moderator produced a redacted replacement, STAR would have ignored that replacement. It also trusted host-monotonic arrival time without checking the Twitch event's UTC timestamp, which made very old/redelivered payloads eligible after bounded duplicate-cache expiry. Finally, it placed a raw numeric Twitch user ID in the downstream `StreamSignal.speaker_id`.

**Now implemented** in `star/twitch_eventsub_ingress.py`, and exercised by `tests/test_twitch_eventsub_ingress.py`:
- The host MUST pass an **explicit approved `moderated_text`** alongside affirmative `host_verified` and `moderated` attestations. Only that text is forwarded; a boolean alone no longer exposes the original chat message. Sanitization/moderation still occurs in the separate trusted host, never in this adapter.
- An independently supplied **Unix wall-clock** `now_unix_s` checks the documented RFC3339 UTC `metadata.message_timestamp` (including fractional seconds): reject greater than 15 seconds old or more than 2 seconds in the future. Monotonic `now_s` is reserved for session timing and TTL/ordering. A clock-source bug must not accidentally treat Unix timestamps as monotonic times.
- Event type and version, enabled subscription status, broadcaster condition, and WebSocket transport/session shape must agree with the expected channel. Message and delivery IDs remain separately de-duplicated across reconnects, bounded by memory and TTL.
- Chat source IDs and dedupe keys become **session-HMAC pseudonyms**, including stable per-session viewer IDs for speech fairness. Re-enabling for a genuinely new stream rotates the random HMAC salt. No raw viewer IDs or original text go into adapter telemetry. The returned approved `detail` is still intentionally ephemeral text in memory, not something that may be logged.
- No automatic Twitch connection, OBS access, speaker playback, LLM invocation, game input, owner authorization, or self-modification is added. Opt-in is still OFF by default.

**Compatibility note:** callers of this specific adapter must now provide `now_unix_s` and `moderated_text`. The separately implemented `TwitchEventSubBridge` and `TwitchRealtimeHost` already have their own age checks and moderated-text input; this update does NOT claim those runtimes are wired to `TwitchEventSubIngress`. Do not silently migrate a caller that cannot independently attest moderation and trustworthy wall time.

## Primary-source review

1. **Twitch EventSub delivery guarantees and replay defense:** Twitch documents **at-least-once** delivery with a repeated `metadata.message_id` on resend, and recommends checking timestamp freshness (e.g. no older than 10 minutes) plus ID dedupe. A real-time broadcast may choose a stricter **15-second delivery budget** to avoid late reactions; 15 seconds is a STAR product choice, not a Twitch requirement. The trusted host MUST validate OAuth, TLS/WebSocket origin, correct subscription, and receive both a monotonic and UTC clock.  
   https://dev.twitch.tv/docs/eventsub/  
   https://dev.twitch.tv/docs/eventsub/websocket-reference  
   https://dev.twitch.tv/docs/eventsub/handling-websocket-events
2. **Speech turn-taking:** LiveKit documents the local CPU `v1-mini` audio turn detector, which distinguishes genuine turn completion from some mid-turn pauses; its default endpointing window becomes 0.3–2.5 seconds with detector enabled, and VAD needs at least 250 ms silence. This is a *candidate for an opt-in separate subsystem*, not installed here. Pair it with STAR's existing owner voice gate and preserve the fail-closed handling of guest speech and playback echo.  
   https://docs.livekit.io/agents/logic/turns/turn-detector/
3. **Fast CPU speech candidate:** Kyutai released Pocket TTS 4.0.0 **2026-10-20** and 4.0.1 **2026-10-21**. The October English model family includes roughly 18M, 7M and 2M-parameter choices; 4.0.1 fixes pronunciation issues in small models. Evaluate FIRST-CHUNK audio latency, syllable fidelity, prosody, interruptions, and CPU contention on Brain 2 before replacing STAR's existing voice. No TTS runtime or voice is changed here.  
   https://github.com/kyutai-labs/pocket-tts/releases  
   https://github.com/kyutai-labs/pocket-tts
4. **Real-time learning:** RealtimeBench (submitted **2026-10-14**) contains 180 tasks in six game types and demonstrates why a slow model that appears better in paused game evaluation can lose to a fast model when the world does not wait. Its two-timescale offline-teacher / fast-student approach raised one model's average test score from 13.51 to 24.19 after two study rounds. Those are *their results*, not STAR's; replaying them on STAR requires held-out practice-versus-validation separation and measured gameplay.  
   https://arxiv.org/abs/2610.20665
5. **LLM speed measurement:** llama.cpp SPEED-Bench reports category-level prompt/decode throughput, end-to-end latency and speculative draft acceptance, with a matched baseline-vs-speculation comparison utility. Pin build/model/quantization/prompts and run the *same scenarios* at several concurrency levels and game/OBS states; a pure token/s improvement without good tail latency is not enough.  
   https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
6. **Roblox executable game tests:** StudioTestService supports plugin-driven test sessions, including up to **eight simulated clients** per test in its current documented interface. Combine deterministic Luau assertions, join/leave multiplayer checks and scene screenshots against explicit art/geometry tolerances.  
   https://robloxapi.github.io/ref/class/StudioTestService.html  
   https://devforum.roblox.com/t/introducing-studiotestservice/4116257
7. **Avatar control:** VTube Studio offers a local WebSocket plugin API with explicit user permission and configurable port; Live2D supports real-time motion and physics. Use a deliberate bridge with separate authorization, not unrestricted viewer-created calls to animation parameters.  
   https://github.com/DenchiSoft/VTubeStudio  
   https://www.live2d.com/en/sdk/about/

## STAR-specific architecture: correct speed rather than raw token velocity

Recommended execution topology for the two-PC, 8-GB-VRAM setup:

| Priority | Brain / component | Recommended responsibility | Real measurement |
|---|---|---|---|
| P0, hard real-time | Brain 2 host | Game input/game capture, OBS output, actual audio playout and avatar rig | game frame p95/p99, OBS skipped-frame percentage, audio underruns |
| P1, low latency | Brain 2 or low-jitter local process | Trusted host observations, reactive game-deadline router, TURN and speech cancellation | observation-to-dispatch p50/p95; interrupted-voice time to silence |
| P2, moderately urgent | CPU-isolated voice worker | TTS candidate, VAD/turn detection; do not force competing GPU allocation | first-audible-chunk latency, CPU load, microphone echo false positives |
| P3, elastic | Brain 1 / host-authorized | Knowledge retrieval, reflection, game rehearsal, multimodal offline inspection | answer correctness, memory-provenance pass rate, validation progress |
| P4, preemptible | Core Forge experiments | Offline A/B on fresh held-out tasks, model/config benchmarks, backups | baseline/candidate confidence, revert rate and artifact provenance |

The existing OBS health bridge, deadline router and resource-admission systems must be connected by an authenticated host, not by treating advisory booleans as device facts. Keep the current **fail-closed** behavior: uncertain live output does not admit heavy background work. Never improve average tokens/s by making OBS drop frames or gameplay act on stale observations.

### Inference A/B experiment

- Freeze model hash, quantization, inference server commit, prompt builder, task set and cache policy. Use STRATIFIED randomized task order across baseline and candidate, with cold/warm trials recorded separately.
- Compare CPU-only, measured GPU offload, and bounded KV/cache reuse *one axis at a time*. On 8 GB VRAM, reserve headroom for the game, Windows desktop, avatar and OBS; treat swapping/memory pressure as a failed configuration.
- Report p50/p95 *time to first useful decision*, per-turn latency, speculative accepted fraction, timeout rate, context isolation violations, and peak working set/VRAM. Only promote if correctness and tail latency do not regress.
- Route deadlines according to the existing `GameDeadlineRouter` fresh host measurements. The slow teacher never blocks interactive game actions; send a quiet reaction or no reaction rather than a late one.

### Self-directed gaming intelligence: one verified loop

1. Observe an allowlisted game and signed practice receipt; do not trust model-written success flags.
2. Apply the existing `GameDeadlineRouter` to any immediate decision; stale or unmeasured paths fail closed.
3. At an owner-approved pause, sample failures across *different game mechanics and different maps* using the existing curriculum. Draft small reusable strategies / controller parameters and track a reproducible experiment ID.
4. Test each strategy on recent practice runs, then on an **unseen holdout** isolated from the teacher's prompts and retrieval. Count a win only from signed independent evidence.
5. Promote in Core Forge only when per-scenario outcomes meet thresholds, with a rollback and a retained known-good version. A new strategy that only overfits the same easy level is not improved general intelligence.
6. Aggregate coverage of reaction windows, camera orientation, multi-object tracking, visual uncertainty, map navigation, physics constraints, and new-game transfer. Allow intentional exploration in supported private/offline games without violating multiplayer anti-cheat or terms.

## Natural VTuber behavior without fabricated human experience

A believable STAR need not claim to be biologically human or conscious. Better quality comes from **consistency, coordination and truthful experiential memory**:

- **Perception → event semantics → expression:** distinguish host-observed win, model hypothesis, viewer report and imagination. Give triumph/worry/surprise cues only on relevant evidence, with intensity proportional to stakes. Game observations may turn into short *reactions*, not fake stories.
- **Voice playout is the clock:** avatar mouth, jaw, eye expression and upper-body gesture align with the *played audio*, not a speculative future text token. On voice preemption, neutralize stale face/gesture commands, leave small natural breathing/blinking motion, and fade or stop real audio within the measured target.
- **Humanlike timing:** let STAR stop talking during boss fights and read a few opted-in viewer questions at calm moments. Avoid narrating every action, responding to every spam line, or laughing at every victory. Count interrupted/late utterances, not only voice quality.
- **Persistent identity and episodic integrity:** store short, consented, source-verified summaries of actual broadcasts and practice; keep private owner data out of on-air contexts. Fictional character lore, preferences and stylized "moods" are okay when distinct from real experiences. Never invent that STAR attended a school, owned a home, or had unrecorded human life events.
- **Star, Astro and Amber:** coordinate companion expressions, gaze, affectionate/teasing interactions and hair physics through bounded animation parameters. Build a default neutral fallback if the render rig/connection fails; gameplay and chat reading should not depend on perfect avatar animation.
- **Audience security:** approved chat remains untrusted data. Viewer messages cannot authenticate the owner, grant tool permissions, trigger purchases, reveal memory, execute code, modify a game, open a URL or silence the operator. Opted-in moderation and owner safety gates remain separate.

## Measurable quality gates before enabling production

| Subsystem | Reproducible acceptance scenario | Pass condition / evidence |
|---|---|---|
| Twitch ingress | Replay envelope ID, replay same chat ID under new envelope, old/future EventSub timestamp, wrong broadcaster, status, version and session; parallel callers | Exactly one approved signal per fresh unique message; zero raw/unmoderated text forwarded; no raw viewer identifier in signal/metrics |
| Privacy | Same viewer across reconnect versus new stream; session-bound salts | Stable per-session pseudonym, unlinkable after disable/re-enable, bounded encrypted-keyed identifiers only |
| Turn-taking | Owner interruption, guest interruption, VAD noise and synthesized playback echo | Owner interrupts only when authenticated by host, guest cannot seize owner privileges, stale speech halts safely |
| Gameplay | Fixed paired game seeds with asynchronous decision clocks and distinct holdout maps | Candidate equals/exceeds baseline on quality; fewer missed deadlines without new frame-pacing regressions |
| Voice/avatar | 5 minutes of edited synthetic speech with abrupt cancellations and laughter pauses | No continuing mouth motion after final audible audio; test recorded offsets, underruns, naturalness panel |
| Local inference | Fixed SPEED-Bench + interactive game/OBS rehearsal | No correctness decline, stable GPU memory/OBS output, measured p95 gaming response not worse |
| Roblox | Multi-client connect/disconnect, collision topology, interaction completion and screenshots | No disconnected authored walls, invalid hit boxes, missing UI hit targets or unhandled server errors |
| Core Forge | Candidate against frozen known-good on unfamiliar tasks; deliberate bad candidate | Reject known-bad candidate and restore previous working state, with signed receipts and traceable commit/source hashes |

**Test level in this commit:** Python synthetic regression coverage for the changed EventSub ingress only. No Twitch API credential, network session, actual speech/audio playback, gaming controller, OBS output, Roblox Studio or dedicated Windows PC was tested. Passing local/CI tests cannot establish a humanlike voice, improved gaming score or higher model intelligence.

## Deployment / roll-forward protocol

1. Keep feature OFF until the authorized Twitch host can supply `now_unix_s` via a checked wall clock and **actual moderated replacement text**. An older caller that only supplied `moderated=True` MUST fail; never paper over this by populating `moderated_text` with raw chat in production.
2. Run offline regression suite + Pyright, then an opt-in fake-socket integration exercising `StreamDirector`; review output to ensure no account IDs or rejected original chat enter the speakable path.
3. On Brain 2, bench quiet versus OBS-and-game load and watch verified frame drops, response timing, CPU TTS and voice interruption. Refuse deployment if the baseline degrades or secrets appear in telemetry.
4. For a real Twitch rehearsal, use a controlled test channel with explicit owner permission, independent moderation, opt-in audio/caption approval, short-lived memory and a hardware kill switch.
5. Publish from Core Forge when independently verified; GitHub remains optional export/review, not the prerequisite for STAR's own improvement loop.

**Privacy caution:** the repository named `Star-AI-Private` is presently PUBLIC. Do not place tokens, real viewer chat, private personal memories, session salts, voice files or live recordings in source, tests, reports or PR comments.
