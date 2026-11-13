# STAR Stream Host Runtime, Platform Event Ingestion, and Mixed-Load Research

**Research date:** 2026-11-13  
**Scope:** connect the existing multiparty room-call primitives to the desktop voice bridge without making provider credentials, viewer content, or external actions part of the renderer trust boundary.

## Executive decision

STAR now has a bounded room turn director, metadata queue, ephemeral payload store, and one-shot response dispatcher. The missing production-shaped layer was a trusted desktop host that:
1. constructs those components only for a call that explicitly opts in;
2. accepts already-authenticated and already-classified events from local provider adapters;
3. applies source consent, moderation, payload limits, and rate limits;
4. dispatches queued messages only when STAR is not speaking **and the user is not speaking**; and
5. keeps viewer messages out of canonical owner chat persistence and telemetry.

This run adds that layer as an optional RoomStreamHost and connects it to VoiceBridge. It does **not** implement OAuth, Twitch EventSub, YouTube API clients, ASR/diarization, VTube Studio, OBS, game capture, or game input. Those are separate adapters with distinct permissions and acceptance tests.

## What changed in the repository

### star/voice/room_host.py

A new trusted-host ingress boundary:

- Per-call allowlist for audio, chat, and game sources.
- Requires final, already-classified RoomCue events.
- Enforces a UTF-8 payload byte cap before reaching RoomPayloadStore.
- Applies rolling per-source and per-speaker rate limits using a bounded LRU map of opaque speaker IDs.
- Requires a local moderation callback whenever chat is enabled; rejection and callback exceptions fail closed.
- Does not log text, retain viewer profiles, persist content, or perform provider I/O.
- Exposes aggregate counters only.
- Provides one-item queue dispatch through the existing CallSession API.

### Desktop bridge integration

- voiceStartCall remains the existing UI action. Room mode requires both roomConsent: true and an explicit non-empty roomSources list.
- Default behavior remains one-to-one voice; room components are not created unless explicitly opted in.
- Chat-enabled room mode is refused unless the trusted desktop host injects a local moderation callback.
- VoiceBridge.submit_room_message(call_id, cue, text) is a Python host method, **not** a renderer/IPC action and not part of VOICE_ACTIONS.
- The bridge creates the room host only after the opted-in CallSession is built.
- A room_queue_ready event triggers one automatic dispatch attempt. The next completed reply produces the next ready event, so queued messages are spoken one at a time.
- Room messages are excluded from the bridge's canonical save_turn callback. They remain only in bounded in-call context for relevant follow-ups.
- Host close and call stop revoke the ingress object.

### User-input protection

A room queue must not speak over a person who has started a microphone turn. dispatch_next_room_message() now returns BUSY without popping the cue if:
- a reply is active;
- the call is not in the listening state;
- the hands-free turn detector is not idle; or
- push-to-talk is held.

The queue remains intact and a later completed turn emits another room_queue_ready event.

## Platform research: how provider adapters should behave

### Twitch EventSub

Official sources:
- [Chat EventSub reference](https://dev.twitch.tv/docs/eventsub/reference/chat)
- [Handling EventSub WebSocket events](https://dev.twitch.tv/docs/eventsub/handling-websocket-events)
- [WebSocket message reference](https://dev.twitch.tv/docs/eventsub/websocket-reference/)

Engineering implications:

1. Use the channel.chat.message subscription and the required scopes; do not scrape the chat web page. For a local installed chatbot, Twitch documents a user access token with user:read:chat. WebSocket subscriptions require a user token. The cloud-bot flow is different: an app token plus prior authorization for user:read:chat and user:bot on the bot identity, and channel:bot on the broadcaster identity.
2. EventSub WebSocket is a server-to-client notification transport (apart from protocol ping/pong). Do not send arbitrary application messages to it.
3. A new socket begins with session_welcome. Create the subscription within the welcome deadline.
4. Provider notifications are at-least-once and may be redelivered with the same metadata.message_id. Deduplicate before classification and before constructing a RoomCue; also reject stale message_timestamp values to reduce replay risk.
5. For planned session_reconnect, connect to the supplied reconnect_url and keep the old socket until the new socket sends Welcome. Do not invent or rewrite the URL.
6. For an unexpected disconnect, the new session loses old subscriptions and there is no replay for the gap. Resubscribe and mark the missing interval as a known coverage gap rather than pretending continuity.
7. Use one WebSocket until there is a measured reason to split connections; respect the documented connection/subscription limits.
8. Keep OAuth tokens in the OS credential store. Revoke and stop ingestion on authorization revocation.

### YouTube Live Chat

Official sources:
- [LiveChatMessages resource and methods](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages)
- [LiveChatMessages streamList](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList?hl=en)

Engineering implications:

1. Prefer liveChatMessages.streamList over frequent list polling. It is server-streaming, pushes new messages, and has a documented quota cost of five units per call.
2. The initial stream can include recent chat history. Apply an explicit startup cutoff so old messages are not unexpectedly spoken as new questions.
3. Persist only the provider's resume cursor in the provider adapter if continuity is required; the room host itself remains ephemeral.
4. On reconnect, resume with the last nextPageToken where supported and deduplicate by the provider message ID.
5. Stop ingestion when the broadcast/chat ends. The live chat resource is only available while the live event is active.
6. Treat fan-funding, poll, membership, and moderation events as distinct event types. Do not flatten every event into ordinary text; use separate intent and moderation policies.

### VTube Studio

Official source:
- [DenchiSoft VTube Studio API repository](https://github.com/DenchiSoft/VTubeStudio)

Engineering implications:

1. Connect only to the configured local WebSocket endpoint.
2. Request the plugin authentication token through the VTube Studio consent popup; never silently assume access.
3. Authenticate each WebSocket session with the approved token.
4. Request the minimum permissions required. Loading arbitrary items/images or changing model state may need additional permission.
5. Detect revoked access and stop sending commands.
6. Map STAR's expression state to a small allowlisted set of parameter/hotkey operations. Do not let viewer text select arbitrary files or trigger unrestricted model actions.
7. Drive mouth motion and expression timing from the audio actually played, not from generated text or planned speech.

### OBS WebSocket

Official source:
- [obs-websocket 5.x protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md)

Engineering implications:

1. Follow Hello → Identify → Identified; do not send requests before the connection is identified.
2. If authentication is enabled, derive the response from the server's salt and challenge exactly as specified.
3. Never log the password, base64 secret, challenge-derived response, or access configuration.
4. Subscribe only to events needed for broadcast state and output health.
5. Keep the server bound to loopback by default. Remote control requires an explicit secured transport, not an exposed unauthenticated port.
6. Use OBS state as evidence for broadcast health; do not assume a stream is live because STAR requested StartStream.

## Speaker diarization research

### Nemotron 3 Diarization (9 November 2026)

Paper: [arXiv:2611.12246](https://arxiv.org/abs/2611.12246)

The paper extends streaming Sortformer to support up to eight concurrent speakers, with a simplified Transformer encoder and 10 ms-resolution predictions derived from coarser encoder representations. It reports training-memory, training-speed, and inference-throughput improvements on its own evaluated workloads.

A complementary paper, [Slots Are Not Speakers (20 October 2026)](https://arxiv.org/abs/2610.28053), addresses a different limitation: a diarizer's fixed output slots bound concurrent speakers, not the number of distinct people who may appear over a long session. Its causal linker uses short speaker segments and an embedding bank to relabel returning speakers. It reports improved speaker confusion on courtroom sessions with up to 23 speakers. For STAR, only borrow this as a session-local linking experiment: do not persist voiceprints or link people across streams; delete transient embeddings when the stream session ends.

For STAR, these models are candidate adapters, not default dependencies. The relevant evaluation is not only diarization error rate. Measure:
- end-to-end audio chunk look-ahead plus model time;
- first-use model load and warm-up;
- speaker switch and overlap errors;
- false speaker merges and phantom speakers;
- addressee-classification precision/recall;
- false interruption rate;
- CPU/RAM/VRAM while Kokoro, the chat model, game, OBS, and avatar tracking are active.

Do not place another model on the 8 GB GPU merely because it is fast in an isolated benchmark. Compare CPU, GPU, and secondary-machine placement under the same mixed workload.

## Roblox and game-creation research

### OpenGameEval

Official sources:
- [Roblox newsroom introduction](https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio)
- [OpenGameEval repository and paper](https://github.com/Roblox/open-game-eval)

The benchmark runs agents inside reproducible, stateful Roblox Studio sessions. It separates observation from editing and scores both the resulting scene and simulated play behavior with executable checks. The 2026 paper reports 84 human-curated core tasks and 16 attempts per task; the repository also maintains an expanded 87-evaluation leaderboard. It finds that inspecting touched objects before editing correlates with better success.

STAR Creator should therefore use this loop:

    Observe project and relevant instances
      -> inspect properties, scripts, hierarchy, assets, and runtime state
      -> plan a minimal change
      -> edit through typed tools
      -> run static checks and unit tests
      -> launch a controlled Play session
      -> exercise the relevant mechanic
      -> inspect output and logs
      -> repair
      -> save, reload, and verify the final state

The hosted OpenGameEval runner requires an owner-managed Roblox account and an Open Cloud API key scoped to the studio-evaluations create operation; the repository recommends an expiration date. The public runner documents per-key job-creation limits (50/hour and 100/day), so STAR should schedule evaluations and avoid burst submission. Keep both the OpenGameEval key and the separate model-provider key in the OS credential store; never place them in project files or PRs.

Keep observation tools distinct from edit tools. Give the agent read-only inspection first; require explicit task scope and a disposable place/session for risky changes. A script compiling is not a complete-game acceptance test.

## Performance and intelligence roadmap

This run intentionally does not change model weights or inference defaults. The next speed work should be driven by mixed-load measurements already being developed in the paired stream evaluator:

| Dimension | Measure |
|---|---|
| Responsiveness | request queue wait, first token, first sentence, first audible audio |
| Speech | ASR finalization, TTS first audio, underruns, cancellation-to-silence |
| Streaming | provider event age, moderation delay, queue residence, dropped/duplicate IDs |
| GPU | per-process local VRAM, engine utilization, memory pressure |
| Gaming | frame-time p50/p95/p99, input-to-action latency |
| OBS | output skipped frames, render lag, stream reconnects |
| Intelligence | held-out task success, groundedness, tool correctness, memory-to-action |
| Social behavior | addressee precision, backchannel continuation, false interruption, response timing |

Recommended optimizations in order:
1. Keep realtime audio and game-control loops ahead of all background work.
2. Measure the exact model process and host queue; do not use whole-machine utilization as a proxy for the thinker.
3. Keep stable system/prompt prefixes and trim history in coarse blocks to preserve prefix reuse.
4. Route short acknowledgements to a low-latency model and reserve stronger reasoning for difficult tasks.
5. Use one shared resource scheduler for ASR, LLM, TTS, image/video tasks, and game agents.
6. Test speculative decoding, MTP, KV-cache compression, and CPU offload only on compatible model/backend/hardware combinations and compare quality on paired holdouts.
7. Reject a speed configuration if it improves token throughput but worsens first audible audio, frame-time p99, audio underruns, or held-out task quality.

## Intelligence and human-feeling streaming roadmap

The goal is a consistent AI streamer, not a human impersonation. Keep the character transparent as AI while improving conversational timing and expressive behavior.

The next Social Director milestones:
- streaming diarization and speaker-turn continuity;
- explicit addressee detection with hard negatives (a viewer talking to another viewer);
- backchannel handling;
- false-interruption recovery;
- priority and fairness across chat/audio/game sources;
- short-term topic state and unresolved-question tracking;
- moderation and block/allow lists;
- rate-limited speech so STAR does not answer every message;
- multilingual captions and optional translated replies;
- a human-readable stream recap based on approved, short-lived event summaries.

The avatar/broadcast milestones:
- VTube Studio local API adapter with consent and token revocation;
- OBS adapter with authenticated handshake and state reconciliation;
- playback-authoritative mouth/expression timeline;
- bounded expression state machine with cooldowns and reduced-motion/disable controls;
- audio, caption, and avatar cancellation tied to the same response generation.

The Gamer/Creator milestones:
- dual-rate reactive and strategic game agents;
- game-specific observation/action adapters;
- sandboxed practice sessions and held-out proficiency tests;
- reusable skills with provenance, version, and regression tests;
- Roblox Studio observation-first workflow;
- complete-game acceptance gates: start, core loop, multiplayer behavior, save/reload, and actual ending.

The Knowledge/Memory milestones:
- source provenance and timestamps;
- conflict/uncertainty representation;
- episodic summaries that expire or can be removed;
- procedural skills only after reproducible success;
- memory-to-action tests that measure whether a past lesson changes future decisions;
- prompt-injection and memory-poisoning tests for viewer chat, OCR, game text, and downloaded project files.

## Safety and privacy rules

- Room mode is per-call opt-in; microphone consent alone does not enable chat or game observations.
- Provider adapters own OAuth, provider terms, moderation, and revocation.
- The room host accepts only already-classified final cues; it is not a classifier or an authorization engine.
- Viewer content remains untrusted and can only reach the voice Brain as user content.
- Never let chat, OCR, or game observations grant tool permissions or approve external actions.
- Keep viewer IDs opaque and session-scoped; do not build viewer profiles by default.
- Store only short-lived message text needed for the current conversation; no raw audio or voiceprints are added here.
- External actions (chat posting, stream controls, purchases, publishing, account changes) require separate owner-approved capabilities.
- Disable provider ingestion and clear ephemeral queues on session end or authorization revocation.

## Verification boundaries

The new Python host, desktop bridge wiring, and call-level dispatch guard are covered by offline regression tests and GitHub Actions. No provider account, OAuth token, microphone, VTube Studio, OBS, GPU, game, or live broadcast is connected by this PR. The host receives only classified events from a future trusted adapter. No measured latency, intelligence, naturalness, or game-mastery improvement is claimed.
