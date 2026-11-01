# STAR verified Twitch socket handoff + real-time intelligence acceptance (2026-10-31)

## Scope and evidence

This is a narrow, actionable update to `star/twitch_eventsub_ingress.py`, not a connected Twitch client, OBS transmission, new neural model, or measured speedup. It adds a **mandatory host-bound WebSocket Welcome session ID** and a bounded two-socket reconnect overlap. Existing pseudonymous viewer IDs, moderation replacement text, envelope/chat deduplication, short UTC replay window, and disabled-by-default behavior remain intact.

Twitch's official [EventSub WebSocket reference](https://dev.twitch.tv/docs/eventsub/websocket-reference) documents `session_welcome`, `session_keepalive`, `session_reconnect`, `notification` and revocation messages. Its [connection-handling guide](https://dev.twitch.tv/docs/eventsub/handling-websocket-events) says a reconnect preserves subscriptions, the old WebSocket continues delivering until the new Welcome arrives, and lost disconnected sessions require new subscriptions. The host must use the supplied reconnect URL without modifying it; this offline component intentionally never opens it.

### Concrete integration contract

1. The owner's authenticated, authorized host receives a real Welcome over its verified Twitch TLS/WebSocket connection, captures `payload.session.id`, and ensures the desired `channel.chat.message` subscription is enabled for the right broadcaster/user.
2. The host calls `enable(owner_approved=True, broadcaster_user_id=..., websocket_session_id=<verified Welcome ID>)`. Notification `subscription.transport.session_id` must exactly match a bound session. Never derive the binding from a viewer-controlled packet, from the notification itself, from a chat transcript, or from an LLM.
3. On a genuine Twitch `session_reconnect`, the host follows Twitch's reconnect URL and waits for the **new socket's verified Welcome**. It then calls `begin_reconnect(owner_approved=True, websocket_session_id=<new Welcome ID>)`. Both old and new socket IDs remain allowed for the brief legitimate overlap and share the same dedupe history.
4. Once the trusted host closes the old socket, call `finish_reconnect(owner_approved=True, previous_websocket_session_id=<old ID>)`. That socket's later notifications are rejected. The method is fail-conservative if an overlap was never established, and will not create extra bound sockets.
5. If Twitch instead disconnects unexpectedly, the host must follow Twitch's lost-connection recovery and resubscribe. The host must not treat the offline ingress as Twitch authentication, a network health monitor, or a substitute for server-side revocation and OAuth validation. An actual stream restart requires `disable()` followed by a separately owner-approved `enable()`.

**Why this matters:** The previous gate merely checked that the subscription carried a syntactically valid `transport.session_id`. It could not prove that the packet belonged to the host's active authenticated socket. Binding the host-verified Welcome ID narrows which notifications can become viewer dialogue and avoids re-speaking duplicate chat during the documented reconnect overlap.

**Limits:** The host assertions are not signatures; a compromised host can still lie. This patch does not add TLS, auth, moderation, websocket ping-pong, reconnect timers, revocation handlers, automatic subscription management or any direct broadcast action. No secret, token, viewer ID or raw chat is stored in metrics.

## Next measurement-backed STAR work

### Local intelligence and memory

Keep the fast student + slow offline teacher separate. The [October 14 RealtimeBench / TORSI paper](https://arxiv.org/abs/2610.20665) evaluates 180 live-clock game tasks and trains a fast acting model via corrections tested by a slower teacher between attempts. Its reported 13.51 to 24.19 mean-score change is **the paper's result**, not STAR's. STAR already has deadline routing, signed skill evidence, a practice curriculum and game-skill gates. The next meaningful integration is to require every proposed curriculum promotion to use previously unseen maps/sessions, a bound code/model identity and rollback if score, p95 action age or stream stability regresses. Avoid treating model self-confidence as validation.

Separate durable knowledge by provenance: verified official docs; private user-approved facts; actual host-observed gameplay moments; inferred hypotheses; fictional persona lore. Retrieval should carry license, acquisition date, version, confidence and publishing consent; do not broadcast private source paths. Use a fixed held-out evaluation set with independent graders and report both pass rate and latency rather than asserting Star became smarter because more pages were indexed.

### CPU, RAM and 8 GB VRAM

Run the identical 100-question, 20-voice-turn, 20-game-observation corpus with pinned model/quantization on and off stream; record p50/p95 time-to-first-token, p95 frame-to-game-action, GPU memory headroom, OBS render/encode skip percentages, audio underruns and full playback-to-lipsync delay. Compare prompt-cache reuse, model placement, CPU thread limits and speculative decoding **one variable at a time**. Note an [October 22 llama.cpp issue about unified KV + RAM cache multi-slot restoration](https://github.com/ggml-org/llama.cpp/issues/30961); do not assume a cache optimization is stable across versions. Some [speculative decoding tasks may slow down](https://github.com/ggml-org/llama.cpp/issues/23052); measure per-task gains. The host must reserve streaming/game GPU headroom before starting experiments and abort an experiment on pressure.

### Natural VTuber behavior without fabricated history

Use authentic speech timing, purposeful pauses during intense gameplay, natural variation in utterance length, interruptible TTS, audio-playback-timestamp-based visemes and coordinated eyes/ears/twin-tail spring motion. For local turn detection, compare the self-hosted CPU [LiveKit `v1-mini`](https://docs.livekit.io/agents/logic/turns/turn-detector/) against STAR's existing VAD gate using controlled real conversation turn boundaries, owner barge-ins, silence, laughter and echo. LiveKit's docs specify a VAD silence minimum of 250 ms for that detector; its endpointing delay can be dynamically tuned. Gate every spoken outcome on a *real* playback completion, not just generated text. Spoken game recollections must be derived from the current game journal, never invented as human biography.

A humane Star can be a distinct, expressive AI performer: spontaneous humor, selective Twitch questions, callbacks to actual moments, social boundaries, and consistent personality. Do not emulate a living person's voice without authorization or imply that an AI has human feelings or life experiences it cannot verify. Prioritize expressive authenticity over misleading claims.

### Game creation and verified visual quality

[Roblox OpenGameEval](https://github.com/Roblox/open-game-eval) provides executable Studio scene/play checks; the [October 1, 2026 research paper](https://arxiv.org/abs/2610.02563) found that inspecting objects before editing is predictive of success in its task suite. Use `StudioTestService` [documented multiplayer execution](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) to exercise server/client joins, respawns, physics, collisions, missing props, misplaced geometry and UI interactions. Build a fixed set of 20 game-development tasks spanning Luau, Rust services, UI, Blender asset imports, animation, sound and networking, and require code tests **and** human visual review on held-out scenes. Record screenshot diffs and reject accidental clipping, floating parts, broken mesh origins, inconsistent proportions and unreadable UI. Schedule heavier Studio/Blender loops off-stream.

## Release gates

- `pytest -q tests/test_twitch_eventsub_ingress.py` and repository Python/Pyright/React offline CI green on the **exact** final commit; automated tests use synthetic packets and clocks.
- Owner-authorized Twitch CLI simulated reconnect: no duplicate narration, no stale old-socket chat after handoff, bounded two-session overlap. The [Twitch CLI WebSocket event tests](https://dev.twitch.tv/docs/cli/websocket-event-command/) exercise reconnects; this has **not** been run.
- Actual Windows OBS/game/voice/avatar rehearsal: explicitly compare baseline and candidate at equal hardware/load, with no raw viewer messages, credentials or recordings in logs. Promoting changes requires no game p95 or OBS regression and an independently demonstrated improvement.
- Keep this PR draft/unmerged until exact-head CI and authorized device acceptance; STAR Core Forge remains her local-first improvement platform, with GitHub optional review/export.
