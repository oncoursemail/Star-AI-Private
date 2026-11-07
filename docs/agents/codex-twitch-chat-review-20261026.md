# Twitch chat independent review — 2026-10-26

Reviewed the new `star/twitch_chat.py` separately from its implementation author. Reviewed source SHA-256: `f5c7d9ce7ff2355e1d7996a5b71cbd9248108501b9d94b2bf6dd51fdba2c42ce`.

**Result:** no remaining blocker found for bundling this read-only adapter at that source snapshot. This review does not approve live account use, broadcasting, automatic speech or a future chat-send feature. The Home bridge and its input/output moderation remain separate integration boundaries.

## Checked boundaries

Token validation is limited to the fixed Twitch HTTPS endpoint, with redirects disabled. The validated client and user IDs must match the configured app and broadcaster, and the token must contain exactly `user:read:chat`. Startup validation and revalidation within 3,500 seconds follow Twitch's [token validation requirements](https://dev.twitch.tv/docs/authentication/validate-tokens/). Failed validation and revocation invalidate pending chat and end the authenticated session. Tokens use the existing native OS vault with no plaintext fallback. Status contains counters and static diagnostic codes.

The adapter requests only the four version-one own-channel message/deletion/clear subscriptions. Their conditions and scope match the [subscription reference](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/). No chat-send, account-creation or stream-key method is present. Incoming text is untrusted content, and receiving or selecting it does not grant moderation approval.

The fixed WSS endpoint, strict reconnect authority checks, subscription inheritance on migration and fresh subscriptions after connection loss match the [EventSub WebSocket protocol](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/). A migration retains the old socket until the replacement welcome; pending messages are conservatively invalidated. WebSocket control frames do not reset the EventSub keepalive clock. The native transport disables tracing and requires certificate and hostname checks.

Queue checks cover bounded storage, TTL, duplicate suppression, delete-before-delivery tombstones, popped-message invalidation, user/channel clear, subscription identity, broadcaster identity and timestamp freshness. Consumers must recheck `queue.current(id)` before later use and separately moderate incoming text and proposed output.

## Finding fixed during review

The original 4,096-entry seen-ID limit could evict a deletion tombstone. Reproducer: remove ID `deleted`, admit 4,096 distinct messages at a fixed clock value, then redeliver `deleted`; it was accepted again.

The author fixed this by invalidating all active/popped messages and pausing admission on overflow. The pause covers the queue TTL plus the permitted 30-second timestamp skew. The receiver also rejects chat at or beyond its TTL. Independent reproduction now rejects the deleted ID, clears active validity, remains paused before the deadline and later resumes fresh admission. The retained verifier includes this regression.

## Executed validation and limits

- `python scripts/verify_twitch_chat.py`: 13 offline cases passed after the overflow fix.
- Ruff on the module and verifier: passed.
- Pyright 1.1.414 on the module with the existing isolated type interpreter: zero errors or warnings.
- Independent in-memory checks passed for deletion/tombstones, queue clear, freshness, own-channel enforcement, reconnect URL rejection and revocation.
- An independent fake migration run confirmed exactly four initial subscription requests, no resubscription on migration, old-socket retention until the replacement welcome, selected-message invalidation and session termination on revocation.

No live Twitch requests, real credentials, account actions or device operations were performed. The optional native WebSocket client was not installed in the verification environment; the retained verifier covers its arguments through a fake module. Actual native transport and an owner-selected Twitch account still require target-PC validation. No existing tests, evaluation fixtures, policy, authentication framework or workflows were edited by this reviewer.
