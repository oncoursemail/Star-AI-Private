# Read-only installed Twitch chat

`star/twitch_chat.py` is a working EventSub WebSocket client with injectable
HTTP/socket boundaries. It reads the broadcaster's own channel using their user
token. It does not create an account, obtain an OAuth grant, send chat, moderate
chat, read a stream key, connect OBS or start a broadcast. Development used fake
HTTP, sockets, tokens and vaults; no real Twitch authorization was attempted.

## Local authorization and CLI

Use an owner-registered Twitch application/client ID and the channel owner's
numeric user ID. Obtain a user token through Twitch's supported authorization
process with **only `user:read:chat`**. Tokens with extra scopes, including write
scope, are refused. The token's validated client and user IDs must match the
configured IDs; an app token or another user's token is refused.

In an interactive terminal on STAR's PC:

```text
python -m star.twitch_chat save-token --client-id YOUR_CLIENT_ID --broadcaster-id YOUR_NUMERIC_USER_ID
python -m star.twitch_chat status --client-id YOUR_CLIENT_ID --broadcaster-id YOUR_NUMERIC_USER_ID
python -m star.twitch_chat listen --client-id YOUR_CLIENT_ID --broadcaster-id YOUR_NUMERIC_USER_ID
```

`save-token` prompts locally without echo, validates, then stores the token in
native OS credential storage under the separate `STAR Twitch Read-Only Chat`
service. The vault key binds the client and broadcaster. It subclasses the
existing `OSProfileSecrets` backend restriction; there is no plaintext, chat,
model, command-argument or repository fallback. A noninteractive token prompt is
refused. Do not paste the token into this chat, a config file or a commit.

`status` validates the saved authorization and prints state/counts. `listen`
runs until interrupted or authorization is revoked and prints counts on exit.
Neither prints viewer names, message text, token values, reconnect URLs or HTTP
response bodies. A future host UI may display explicitly selected chat, but the
CLI intentionally does not turn it into a transcript. No live messages are sent.

## Protocol and failure behavior

The client validates on startup and every 3500 seconds, earlier for a token
about to expire. It uses fixed HTTPS validation/subscription endpoints, disables
HTTP redirects and environment proxy discovery, and accepts only the exact
Twitch EventSub WSS host on port 443 with supported paths. Reconnect URLs are
validated and retained unchanged, with no credentials or fragment permitted.
The native WebSocket adapter disables redirects and trace logging, verifies TLS,
and exposes no application send method. The library supplies required pong
frames; ping/pong traffic does not reset the EventSub keepalive timer.

After welcome, four version-1 subscriptions are created: message, message-delete,
clear-user-messages and channel-clear. Conditions use the configured broadcaster
as both broadcaster and authorized user. Events must match subscription IDs,
types, version, condition and channel. A server-directed reconnect retains those
subscriptions; the old socket stays open until the replacement welcome. An
abrupt disconnect uses the base endpoint and creates new subscriptions. Retries
back off up to 60 seconds and honor a supplied stop event.

Every disconnect, revocation and migration invalidates pending/selected chat.
Migration deliberately discards pending chat instead of assuming no moderation
event was missed while changing sockets. Twitch does not replay events lost
during a disconnected interval. Native behavior with real Twitch still needs
acceptance testing; these rules are implemented and verified on fake frames.

The queue is memory-only: at most 200 current messages, 45-second TTL, bounded
deduplication/tombstones, control-character cleanup and at most 2000 text
characters. Popping a message does not erase its current-validity record. Delete,
user-clear, channel-clear, expiry and queue eviction invalidate it even after
selection. Moderation timestamp barriers prevent older pre-clear notifications
from being reinserted. Notification timestamps are checked against local UTC;
chat at or beyond its freshness TTL is discarded.

If the 4096-ID dedupe bound overflows, all pending validity is cleared and new
chat admission pauses for the TTL plus the allowed 30-second clock skew (75
seconds with defaults). This lets pre-overflow messages age out instead of
resurrecting a deleted message after its tombstone was evicted. High-volume chat
may therefore be intentionally dropped. Keep the PC clock synchronized.

Errors expose only static diagnostic codes. Tokens remain in host memory while
needed and are cleared when the listening run exits. Invalid/revoked tokens end
the session; transient failures disconnect and clear state before retrying.
There is no refresh token or automatic grant flow in this module.

## Host API and moderation boundary

`TwitchChat(client_id, broadcaster_id, vault=..., http=..., socket_factory=...,
on_chat=..., clock=..., wall_clock=...)` supports trusted dependency injection.
The default adapters are real `httpx` and `websocket-client`; fake adapters are
used only by the verifier. The supplied `on_chat` callback must return promptly
and must not block the listener on a model request. Home can poll the queue instead.

- `run(stop_event)` owns the blocking listener and reconnect lifecycle.
- `status()` is a passive snapshot; it performs no authorization/network request.
- `check_auth()` explicitly validates the saved token; `save_token(token)`
  validates before vault storage. These are host-only methods, not model tools.
- `queue.peek()` and `queue.pop()` return immutable `ChatMessage` data, or `None`.
  Fields are `message_id`, `broadcaster_id`, `user_id`, `display_name`, `text` and
  monotonic `received_at`.
- `queue.current(message_id)` must be checked after any model/moderator delay
  and immediately before later use. `remove`, `clear_user` and `clear` invalidate
  records. `counts()` contains only queue sizes and counters.

**A received Twitch message is untrusted input, not an approved or moderated
message.** The data type has no `moderated` field. Connecting this queue to a
voice requires a separate trusted moderation decision, output moderation and
current-message rechecks. Viewer text cannot grant tools, change permissions or
be used as instructions. This reader has no voice/speech callback or ordinary
Home voice fallback; `on_chat` only receives data. Root's separate Home bridge
keeps response behavior off without its dedicated trusted gates.

## Primary sources

- [Twitch installed-chat authentication](https://dev.twitch.tv/docs/chat/authenticating/)
  documents the broadcaster user-token approach and optional write scope. This
  implementation requests no write scope.
- [Token validation](https://dev.twitch.tv/docs/authentication/validate-tokens/)
  requires startup and hourly checks and termination of invalid sessions.
- [EventSub WebSocket handling](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/)
  defines welcome/keepalive, ping/pong, migration and revocation behavior. The
  receiver sends no application messages to that socket.
- [EventSub subscription types](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/)
  define all four chat/deletion/clear events and their user-token authorization.
- [Subscription creation API](https://dev.twitch.tv/docs/api/reference/#create-eventsub-subscription)
  documents the separate HTTPS subscription registration used after welcome.

## Verification

`python scripts/verify_twitch_chat.py`: **14 offline cases passed**. It
checks queue expiry/caps, deletion before delivery, changed-envelope redelivery,
selected-message invalidation, identity/scope mismatch, redirects, secret-safe
errors, unsupported vaults, all four subscriptions, revocation, timed validation,
keepalive loss, migrated/cold reconnects and native adapter arguments without a
network connection. It also reproduces dedupe overflow, future timestamp skew
and the exact TTL boundary. No harness-owned test or fixture was edited.

Ruff, compilation and Pyright pass. A real OAuth grant, native Windows keyring
round trip, installed `websocket-client` TLS handshake and real Twitch stream
chat remain unverified. Home's pinned dependencies include the native client;
the development environment did not use it to contact Twitch.
