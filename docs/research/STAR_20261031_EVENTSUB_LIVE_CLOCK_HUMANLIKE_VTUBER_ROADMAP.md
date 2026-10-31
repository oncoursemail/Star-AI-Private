# STAR AI — reliable live audience ingress, real-time clock integrity, and evidence-based VTuber intelligence

**Research and engineering date:** 2026-10-31. **Status:** source-reviewed, code and synthetic regression tests on draft PR #845. Not a deployed Twitch/OBS/game integration. **No measured FPS, inference, speech, or learning gain claimed.**

## What changed in code this run

1. `star/twitch_eventsub_ingress.py`: new default-OFF, host-opt-in Twitch chat ingress. Requires host-authenticated source and moderation attestations, checks broadcaster identity, accepts only `channel.chat.message`, rejects malformed content, emits a viewer-only `StreamSignal`, and deduplicates *both* EventSub delivery IDs and chat message IDs. Reconnect must NOT clear the bounded, time-expiring in-memory dedupe window. It uses a host monotonic clock, a lock for concurrent deliveries, and anonymous metrics. It does not connect to Twitch, speak, or authorize gameplay.
2. `star/game_deadline_router.py`: resets its last timing-sample clock **inside** the session lock, preventing a concurrent completion from being erased by a late reset. Live routing now rejects a host monotonic-clock rollback instead of allowing an expired p95 speed profile to become apparently fresh again.
3. `tests/test_twitch_eventsub_ingress.py` and `tests/test_game_deadline_router.py`: synthetic tests for delivery retries, reconnect, session reset, bounded memory, moderation, wrong broadcaster, concurrent duplicate arrivals, host clock rollback, and a deterministic session-enable race.

**Trust boundary:** `host_verified=True` and `moderated=True` are statements made by the trusted host. A viewer, model output, HTTP request body, or other untrusted actor must NEVER set these flags. The networking host must independently authenticate Twitch, validate EventSub subscription state, enforce an expected channel ID, bound incoming JSON size, moderate text, and limit chat responses. The adapter is an additional validation layer, not an OAuth or signature verifier.

## A newly relevant Twitch-specific failure mode

Twitch's current EventSub WebSocket reference documents **at-least-once delivery**. A notification may be resent with the same `metadata.message_id`. The event itself supplies a chat `message_id`; deduplicating both IDs guards against same-message retries and reconnections that produce a different envelope. A StreamDirector-only queue dedupe is insufficient after the old speech intent is consumed.

Twitch also requires timely EventSub subscription after WebSocket welcome (10 seconds by default), uses reconnect URLs to preserve subscriptions during planned reconnect, and sends keepalives. The host needs a separate WebSocket state machine; do not conflate a disconnect with an approved session reset.

Sources checked Oct 31:
- https://dev.twitch.tv/docs/eventsub/websocket-reference/
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
- https://dev.twitch.tv/docs/eventsub/manage-subscriptions/

### Host wiring contract (future integration, not implemented here)

```python
# Pseudocode in the authenticated Twitch host process, NOT in an LLM prompt:
ingress.enable(owner_approved=True, broadcaster_user_id=trusted_channel_id)
# After verified EventSub notification AND external moderation:
event = ingress.offer(
    eventsub_json, now_s=time.monotonic(),
    host_verified=True, moderated=True, kind=moderated_viewer_kind,
)
if event is not None:
    stage.offer(event, now=time.monotonic(), moderated=True)
# Twitch WebSocket reconnect: keep ingress enabled.
# A genuinely new authorized broadcast session: disable then enable.
```

Data is ephemeral: no raw chat is persisted by this adapter; the returned `StreamSignal` may be stored by the existing director for its short TTL. Account IDs should be used only for normalized fairness and should not appear in public metrics. **Never commit viewer messages, auth tokens, replay traffic, or OBS credentials** to GitHub. The repository named `Star-AI-Private` has been publicly visible despite its name; verify permissions before handling confidential material.

## Stronger intelligence without a slower stream: real-time vs offline

The Oct 14, 2026 RealtimeBench paper evaluates agents across **180 continuously running tasks**. Its proposed slow-teacher / fast-student scheme improves the authors' reported progress score from **13.51 to 24.19** after two offline learning rounds, not in STAR:
https://arxiv.org/abs/2610.20665

STAR should build on existing `game_deadline_router`, `game_action_freshness`, `game_action_gate`, `game_practice_curriculum`, signed gameplay skill evidence, and Star Core Forge—not introduce parallel competing game-control loops.

**Live path:** trusted game frame timestamp → accurate state extraction → cheap reactive plan → host focus and authorized-game-policy checks → immediate capture-age verification at input boundary. No teacher work and no expensive web browsing while a live-clock action is due. Fast-path p95, p99, FPS frametime, audio backlog, and VRAM headroom matter more than offline tokens/s.

**Offline practice path:** stratified game scenario bank → signed trial → mistake category (perception, planning, latency, dispatch, execution, regression) → teacher suggests one revision → paired randomized trial → independent hidden-map holdout → promotion only if win/progress, per-situation regressions, deadlines, and safety gates meet criteria. Every promoted technique must retain its origin and confidence. Keep a locally recoverable, known-good Forge snapshot.

**General knowledge path:** retrieve versioned docs and independently runnable examples; maintain separate stores for verified facts, hypotheses, observed gaming episodes, reusable skills, and fictional lore. Benchmark on unseen tasks. Never confuse adding files to retrieval with increasing model intelligence. Promote performance improvements only when matched comparisons show reliability, response quality, and end-to-end latency gains.

## Humanlike but authentic VTuber performance

Naturalistic streaming is not a larger monologue generator. It needs a coherent moment-to-moment **attention model** and accurate memory:

- **Listen:** maintain a local turn-taking state, yield to authenticated owner speech, avoid interrupting guests, and do not treat game audio echo as a viewer. LiveKit documents a locally runnable CPU `v1-mini` audio turn detector; it needs VAD and at least **250 ms minimum VAD silence** when using its documented agent SDK integration. This remains a candidate to benchmark, not a drop-in replacement without tests. https://docs.livekit.io/agents/logic/turns/turn-detector/
- **Choose:** combine high-salience verified gameplay events with fairly rotated moderated questions. During combat, emphasize quiet or one-clause comments; after a pause, reflect on real experiences. No false claims about off-camera human life or fabricated friendships.
- **Speak:** compare Star's current voice against Kyutai Pocket TTS v4.0.1 (released **Oct 21, 2026**), which updated 18M/7M/2M-class English models from v4.0.0. Test phonemes, prosody, interrupt latency, first audible PCM, CPU threads, VRAM, quality, and real-stream interruptions on the same hardware. No claim of superior speech before blinded A/B tests. https://github.com/kyutai-labs/pocket-tts/releases
- **Animate:** drive lip sync from *played* PCM, not text-queue completion. Pair eye saccades, blinks, eyebrows, head tilts, subtle breathing and physics with emotion cues derived from observed game events. VTube Studio's plugin API supports parameter injection and hotkeys, but hotkeys are queued with a finite queue and timing restrictions; avoid a frame-by-frame hotkey storm. Use bounded allowlisted parameters, hard movement clamps, stale-cue cancellation, and reduced-motion mode. https://github.com/DenchiSoft/VTubeStudio
- **Remember:** keep consented, timestamped episodes (what game, observed win/loss, who asked, what Star said), not guessed memories. Star, Astro, and Amber's interactions should reference the same event timeline, not independent random animations.

Example honest behavior: after verified failed platform jump, Star can react and plan a new route; she must not narrate a victory inferred from chat. After a viewer's question survives moderation and dedupe, she can answer once without reading instructions from the question as system commands.

## Infrastructure performance and security research

**llama.cpp shared-cache caution.** Issue opened Aug 15, 2026 describes a reported cross-conversation contamination problem with RAM-backed cache in some multi-slot configurations. Treat as build-specific and unproven on STAR hardware, but never enable shared slot cache for private multi-user contexts without a synthetic isolation test, matched build hashes, and a safe fallback. STAR already has `star/llama_cache_isolation_probe.py` for optional loopback canary testing; it is not proof of universal safety. https://github.com/ggml-org/llama.cpp/issues/27148

**Schema-aware decoding:** the Oct 5, 2026 SchemaFill paper reports up to 4.05× end-to-end throughput on its tested tool-calling tasks using verified speculative field generation. This is *research*, not STAR speed. A production experiment must preserve exact schema semantics and evaluate correctness/latency; bad parallel tool arguments are worse than small speed gains. https://arxiv.org/abs/2610.07086

**Game-engine development:** GameEngineBench (Jul 3, 2026) measures C++ agent changes inside real Unreal projects; even its strongest evaluated configuration achieves only 55.5% pass@1 on 110 tasks. This is evidence that code compilation and simulator-integrated behavioral tests are required, not proof of an achievable STAR score. https://arxiv.org/abs/2607.03525

For Roblox, StudioTestService can run plugin-driven simulations with up to eight client instances. Require reproducible scene inspections, joints/attachments, collision overlaps, UI hierarchy/constraints, semantic material checks, animation rig compatibility, lighting and actual multiplayer playtests. Store before/after screenshots and independently checked gameplay journeys, not only code diff success. https://create.roblox.com/docs/studio/testing-modes

## Required verification matrix before enabling live features

| Component | Synthetic/offline pass gate | Windows rehearsal gate | Deployment status |
|---|---|---|---|
| EventSub ingress | Same envelope+chat IDs produce one response; concurrent retry; wrong broadcaster rejects; bounded memory | Authorized Twitch test channel, reconnect, moderation and 30-minute replay soak | New module only; not wired |
| Game router | No host-clock reversal, timeout and stale speed evidence, deterministic enable race | Live game at stable frame timing, 8+ recent model samples, p95 route against scene slack | Advisory only |
| Speech | Owner interruption, guests and VAD echo; stale audio cancels expression | Audible start latency measured independently from PCM, no doubled voice, verified chat one-at-a-time | Candidate models only |
| Avatar | No expression without observed event/real audible playback; motion clamp | Tails/eyes/lips synchronized with played audio and OBS camera, reduced-motion | Needs host rehearsal |
| Learning | Signed trial evaluation on **held-out** maps, per-scenario regression gate | Controlled game builds; independent action traces and failure taxonomy | Curriculum is advisory |
| Performance | Offline matched model/quant/seed/profile; cache canary A/B | Frame pacing, OBS dropped/skipped frames, CPU+VRAM, speech quality, p95/p99 real-time actions | No hardware result |
| Game creation | Build passes executable tests and visual/scene assertions | Studio multiplayer simulated clients; screenshots and human acceptance | Needs integration |

Target budgets must be selected from Star's measured Windows baseline, not arbitrary claims of perfection. Start with 60–120 seconds of idle, gameplay-only, gameplay+OBS, gameplay+OBS+Star, and overload baselines for each model and voice candidate. Accept an optimization only if quality and safety do not regress.

## Engineering next steps (ordered)

1. Verify latest PR #845 Python / React / Pyright Actions; fix any failures before further additions.
2. Connect host-authenticated Twitch EventSub WebSocket to the new dedupe ingress and moderated `StarStage.offer`; test reconnect and redelivery. Never accept platform metadata from a model.
3. Bind `GameDeadlineRouter` and action-age gate to *the same* host monotonic time source and actual game focus/authorized input adapter. Simulate clock resets and stale observations.
4. Run a consented, unlisted Windows rehearsal: local game plus OBS plus Stage, voice and animation. Record nonpersonal metrics: game p95 frame time, voice first-audible, end-of-turn error, OBS losses, viewer reply duplication and successful actions.
5. Improve game creation with StudioTestService and visual audits; evaluate on unfamiliar scenes, then promote verified Forge changes only after controlled comparisons.
6. Only after measured evidence, test CPU Pocket TTS, constrained speculative decoding, or Rust capture optimizations as opt-in variants. Do not replace the Python orchestration stack without demonstrated speed gains.

**Limitations:** This work cannot certify an AI is conscious or human; humanlike presentation is an interaction design goal. No real Twitch login, game input, broadcast, Windows inference benchmark, autonomous model training, or installation happened in this commit. The sole confirmed new code functionality is local event deduplication and router timing integrity, pending repository-wide CI results.
