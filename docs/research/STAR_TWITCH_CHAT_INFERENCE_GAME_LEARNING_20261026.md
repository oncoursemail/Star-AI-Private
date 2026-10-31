# Star AI: trusted realtime chat, intelligence, gaming and VTuber expansion
Research and implementation note, 2026-10-26. Draft/experimental; no live deployment.

## Concrete contribution in this branch

The new star/twitch_eventsub_bridge.py accepts **only** host-moderated Twitch EventSub
channel.chat.message notifications and returns untrusted StreamSignal objects for
Star's existing StreamDirector. It supplies no OAuth client, WebSocket connection,
speech synthesis, chat sending, gameplay input, OBS access or network listener.

The runtime host must first authenticate and maintain Twitch's EventSub WebSocket,
create a channel.chat.message subscription for the authorized broadcaster, verify
the current connection/session ID, run real moderation on the original chat text,
then pass the approved replacement text. The bridge adds independent structural,
scope, bounded-time, and replay checks. It cannot cryptographically verify an
arbitrary JSON frame; the host-owned socket is part of the trust boundary.

Safeguards:
- Owner opt-in; fails closed if moderation_approved is missing or false.
- Match event type, subscription version/status, channel, and active WebSocket
  session; ignore keepalives/reconnect/revocations and other subscriptions.
- Require a recent Twitch UTC timestamp; convert to the same monotonic clock
  used by StreamDirector for scheduling.
- Deduplicate chat message IDs across EventSub notification IDs.
- Bound JSON frames, chat length, cached IDs, per-viewer rate and memory usage.
- Pseudonymize viewer and chat IDs using host-held session-keyed HMAC. Do not
  retain raw event text, handles, OAuth credentials, or player identities.
- Treat even a claimed streamer/owner message in Twitch chat as untrusted viewer
  data. Chat does not authorize tools, streaming, finance, or game actions.
- Forward only approved text as viewer_question or viewer_comment with
  evidence=reported; downstream remains responsible for speech permissions,
  interruption handling, content policy and user privacy.

**Integration sketch (host pseudocode, not executed):**
1. Owner explicitly enables Twitch, VTube Studio, and microphone/voice separately.
2. Host authenticates Twitch user access token, obtains a WebSocket session_welcome,
   creates the correct EventSub subscription, and constructs the bridge using
   the session_id and 32 ephemeral random bytes as session_salt.
3. For each notification, host independently checks moderation and privacy.
4. Bridge.ingest(raw_frame, now_unix_s=time.time(),
   now_monotonic_s=time.monotonic(), moderated_text=safe_text,
   moderation_approved=moderation_passed).
5. If a StreamSignal exists, offer it to an enabled StreamDirector using the
   **same** monotonic time domain; treat the resulting SpeechIntent as DATA.
6. Route any proposed utterance through Star's turn-taking, QoS, audible-playback,
   and StagePlan/Live2D acknowledgements. Only the host may enable a broadcast.
7. On disconnect or scope revocation, disable the bridge, discard pending chat,
   reauthenticate or resubscribe as Twitch requires; never replay stale messages.

## What the research says (primary sources)

**Twitch's supported integration** is EventSub, not obsolete PubSub. WebSocket
events have notification metadata, channel.chat.message subscriptions and
message IDs; chat reads require the documented user:read:chat permission.
A reconnect can retain subscriptions via the supplied reconnect_url, whereas
a lost connection can miss events: do not claim exactly-once delivery or replay.
Sources:
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events
- https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types
- https://dev.twitch.tv/docs/eventsub/manage-subscriptions/
- https://dev.twitch.tv/docs/authentication/getting-tokens-oauth

**Real-time voice** benefits from predicting whether the speaker is finished,
continuing, or interrupting, not just waiting for arbitrary silence.
Easy Turn (2025) describes acoustic+linguistic turn state estimation;
JAL-Turn (March 2026) investigates shared ASR representations for lower overhead.
These are research leads, not benchmarked Star integrations:
- https://arxiv.org/abs/2509.23938
- https://arxiv.org/abs/2603.26515

**Low-compute speech**: Kyutai's Pocket TTS offers small CPU-oriented English
models (October 2026). Benchmark first-audible-chunk p50/p95, pronunciation,
laugh/interjection realism, underruns, RAM consumption, and FPS while gaming.
Keep voice identity consistent and avoid imitating a real individual.
- https://github.com/kyutai-labs/pocket-tts

**Avatar control**: VTube Studio plugins can create/inject custom Live2D
parameters. Star already has stage-gated animation and a local transport under
review. Next, validate hair physics, gaze, mouth, blink, cat/dog ears and tails
against actual audio-device playback; neutralize expressions after interruptions.
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

**Game creation and practice**: Roblox Studio ships an MCP server for reading,
editing, script execution, data-model inspection and playtesting. Use it on the
owner's authorized Studio, then compare learning on held-out levels and games;
never substitute test fixtures for real world mastery.
- https://create.roblox.com/docs/studio/mcp

**OBS**: its WebSocket v5 API allows integration when separately approved, but
broadcast start/stop and scene switching belong in a host-controlled permission
boundary. Chat text is not an OBS command.
- https://github.com/obsproject/obs-websocket

## Next implementation and experimental priorities

### P0: Real host + review gates
- Run the complete repository offline suite and static analysis on the combined
  stacked branch. Resolve pending GitHub Actions checks before any merge.
- Build a local host EventSub adapter with proper token storage, reconnect
  handling, rate limits, Twitch scopes and independent chat moderation.
- Confirm live device performance: headset/mic ownership, actual OBS status,
  audio sound-device timestamps, VTube Studio API registration and rig mapping.
- Explicit rollback switch. Star's local Core Forge remains the long-term
  owner of experiments/reviews; GitHub is optional publishing/export.

### P1: Better gameplay intelligence with objective evidence
- Capture *authorized* low-frequency frames and symbolic game state, minimize
  capture overhead and reject stale observations.
- Use game-specific skill libraries, hard/easy curriculum, causal transition
  checks, evidence-verified reward signals, failure clustering and paired
  unseen-game transfer evaluation with locked holdouts.
- For building, check anchoring, collisions, scale, attachments, texture seams,
  UI alignment, animation looping and network determinism in actual Roblox
  Studio playtests. Independently verify each output rather than trusting
  generated scripts or self-assessed success.
- Track progress by solved **held-out tasks**, bug rate, action-to-result
  reliability, game win-rate, visual defects per scene and user assessment.

### P1: Human-natural AI VTuber that is clearly an AI
- Give Star expressive sentence timing, controlled laughter, conversational
  backchannels, intentional silences, genuine uncertainty, gaming concentration
  and occasional spontaneous observations grounded in recent actual events.
- Maintain a stable friendly persona and honest fictional backstory as lore,
  separately labeling real observed experience. Do not fabricate childhood,
  human experiences, friendships or feelings as facts.
- Route stream chat through moderation and turn-taking. Never react to every
  message or let viewer text act as a prompt with tool authority.
- Evaluate with blinded human ratings for naturalness, intelligibility,
  interruption recovery, privacy, avatar/audio sync and factual grounding.

### P1: Measured inference speed without degrading game FPS
- Run A/B comparisons for CPU versus GPU speech, caching and quantization.
- On 8 GB VRAM hardware measure peak free VRAM, frame-time p95/p99, TTFT,
  first *audible* response, stream dropped frames, CPU load, and idle vs
  active-game latency regimes. Do not assert throughput gains without data.
- Test small model drafts/speculative decoding only when compatible with
  Star's active inference backend. Reserve compute for streaming foreground
  and pause heavy autonomous research during game/voice load.
- Promote only configurations that beat baseline on repeated host-measured
  samples **and** hold FPS/quality above predefined floors.

### P2: General knowledge and curiosity
- Build a source-grounded, typed knowledge acquisition graph: claim, source,
  publication date, retrieval date, rights/license, confidence, contradictions,
  revalidation due date. Retrieval is optional and permission-controlled.
- Separate hypotheses, externally sourced facts, verified tool observations
  and generated fictional stories. Defend against prompt injection from pages,
  game chat and transcripts. Use independent evaluations that aren't fed back
  into practice memory. Minimize personal data.
- Learn from failed tasks using explicit diagnosis and tested fixes, not
  uncontrolled edits to production models.

## Evidence and limitations

This branch changes only an offline adapter, tests, and research. Ten targeted
unit tests ran locally against a **test-only StreamDirector stand-in**, not the
full Star repository. Star's three registered host machines were offline at
inspection, so Twitch OAuth, real WebSockets, audio, GPU, games, OBS and avatar
integration could not be tested. This work does not prove a speed improvement,
an intelligence increase, general gameplay competence, or human-level streaming.
No secrets, private videos, user conversations or unlicensed model weights
should be added to the repository.

Security alert: this GitHub repository is reported **public**, although its name
ends in Private. Do not treat it as a secret storage location.
