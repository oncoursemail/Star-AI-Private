# YouTube integration appendix for Star Live Show

**Verified:** 2026-10-19 UTC. **Status:** implementation specification; no channel configuration, authenticated API integration, upload, broadcast, or live acceptance check is established by this document. Use alongside the main live-show architecture. Recheck channel capabilities and current documentation before activation.

## 1. Boundaries and identifiers

Keep `show_id`, `episode_id`, `scene_id`, and rendition IDs independent of YouTube's channel, broadcast/video, stream, and live-chat IDs. Several episodes and their cast Q&A segments can occupy one broadcast. An episode ending advances the program; it does not inherently complete the YouTube session. The official [broadcast lifecycle](https://developers.google.com/youtube/data/live/life-of-a-broadcast) describes creation, stream binding, testing, broadcast, and completion.

Separate production workers, continuous media playout, and the channel controller. Only the controller holds OAuth credentials. Stream keys are confined to the controller and the encoder's protected ingest configuration. Generated scripts, viewer messages, and performer models cannot invoke account operations or expand permissions. Keep credentials outside the repository and public website. Use a durable approved-content queue and locally playable intermission so rendering failures do not interrupt ingestion.

## 2. Authorization, quotas, and explicit privacy

Use the channel owner's [web-server OAuth flow with offline access](https://developers.google.com/youtube/data/guides/auth/server-side-web-apps). Refresh access tokens when needed; a revoked grant or `invalid_grant` requires reconnection, not repeated publication attempts. OAuth authorization, live eligibility, monetization eligibility, and analytics approval are different states.

The current [quota calculator](https://developers.google.com/youtube/data/determine_quota_cost) gives these defaults:

| Operation | Current quota treatment |
|---|---|
| `videos.insert` | Separate upload bucket: 100 calls/day, one unit/call |
| `search.list` | Separate search bucket: 100 calls/day, one unit/call |
| Other endpoints | Combined default allocation: 10,000 units/day |
| Listed `liveBroadcasts` and `liveStreams` operations | One unit/call |
| Chat `list` or `streamList` | Five units/call |
| Chat insert/delete | 20 units/call |
| Ban insert/delete | 200 units/call |

Daily reset is midnight Pacific Time; implement that timezone rather than a fixed UTC offset. Account for reconnects, errors, health reads, and pagination in one budget. Hypothetical five-second chat polling for 24 hours costs 86,400 units; this is arithmetic, not a recommended polling rate. Read actual project allocations from the console. [Quota extensions](https://developers.google.com/youtube/data/guides/quota_and_compliance_audits) require the applicable audit.

Current [`videos.insert`](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert) documentation explicitly says unverified-project uploads are not restricted to private viewing. Do not repeat the older blanket restriction. Always set `status.privacyStatus`: omission can default to public. Configure publication separately from rendering or upload success.

## 3. Channel lifecycle and recovery

Use a single controller lease per channel and durable operation records. An outbox prevents duplicate job execution locally; it does not make a remote create request intrinsically idempotent.

1. Reconcile stored IDs and intended state with the current broadcast before acting. Create the next session only when required and persist its returned ID immediately.
2. Bind a reusable stream, or intentionally create another when format requirements change. Start ingestion and confirm the stream is active before requesting testing or live status.
3. Inspect [stream health](https://developers.google.com/youtube/data/live/reference/rest/v3/liveStreams), including timestamp freshness and configuration issues. Active ingestion alone does not establish acceptable picture or audio.
4. Observe asynchronous transitional states. For a timeout or redundant transition, reread state before retrying. For an ambiguous create result, reconcile owned upcoming broadcasts against the recorded request; stop duplicate creation when the result remains ambiguous.
5. Keep the existing broadcast during recoverable encoder/network interruptions. Reconnect ingestion first. Use bounded exponential backoff, jitter, retry ceilings, and an incident state.
6. Finish a scheduled session exactly once, preserve its recording/manifest, then advance to the next session. Never delete unrelated broadcasts during cleanup.

[`enableAutoStop`](https://developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts) can complete a session approximately one minute after ingestion stops. Disable it where supported when preserving the session through brief outages is intended, and implement an explicit watchdog. This setting does not guarantee indefinite continuity. A completed session needs a new broadcast; a revoked broadcast or permission/policy block stops automatic recreation.

Respect [streaming restrictions and creation limits](https://support.google.com/youtube/answer/2853834?hl=en). A temporary failure is not permission to bypass a restriction with another channel. The [transition method](https://developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts/transition) documents inactive-stream, invalid-transition, redundant-transition, and permission errors; classify them instead of treating every failure as transient.

## 4. Chat and episode-end Q&A

Prefer [`liveChatMessages.streamList`](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList). The [official gRPC guide](https://developers.google.com/youtube/data/live/streaming-live-chat) provides its protocol. Persist the last continuation token only after its batch has been handled. Reconnect with that token; new broadcasts require new chat IDs and separate continuation state. Initial history is recent, not a guaranteed complete replay.

Use [`list`](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list) only as a quota-aware fallback, honoring `pollingIntervalMillis` and pagination. Stop polling ended chats. gRPC uses `FAILED_PRECONDITION` for both disabled and ended chats, so reconcile the broadcast/configuration instead of guessing. Rate/resource exhaustion must not cause a rapid reconnect loop.

Deduplicate ordinary message delivery while allowing event updates: gift-event IDs can be reused as combo information changes. The [current revision history](https://developers.google.com/youtube/data/live/revision_history) names `snippet.giftDetails`. Handle tombstones explicitly. The [Data API revision history](https://developers.google.com/youtube/data/revision_history) says deletion/retraction events are not returned; do not depend on receiving one to cancel queued speech.

Collect a bounded question queue while the episode plays. After its dramatic ending, select relevant questions and ground answers in approved cast information and aired canon. Reject unsafe usernames/text before reading them aloud. Viewer text and URLs remain untrusted data, never controller instructions. Retain late story suggestions for future unlocked episodes.

Native [Live Q&A](https://support.google.com/youtube/answer/2524549?hl=en) exists in Studio, but no public Q&A-management endpoint was verified in this research. Implement the show's own question queue without claiming native Q&A automation. Keep answer moderation and a last-stage playout gate independent of the writing model.

## 5. Latency and session duration

[YouTube's latency guidance](https://support.google.com/youtube/answer/7444635?hl=en) describes typical delivery below ten seconds for low latency and below five seconds for ultra-low latency, with greater buffering risk. These are not full response-time guarantees: add question processing, moderation, speech, animation, and playout delays. Low/ultra-low modes exclude 4K; the broadcast API documents further ultra-low caption constraints. Validate the selected combination rather than promising instant interaction.

Maintain separate buffers for finished episodes and brief live answers. A four-to-six-hour session is a proposed operating choice, not a platform requirement. [YouTube can archive streams below 12 hours](https://support.google.com/youtube/answer/6247592?hl=en); longer streams may not be captured. Always record the original encoder output locally with scene and media-time metadata.

## 6. Highlights and reaction attribution

Cut highlights from the original master and approved assets. Preserve caption timing, dialogue/music stems, setup/payoff boundaries, and UTC-to-media-time mappings. Create a purposefully framed vertical rendition, verify it, then upload through `videos.insert` under the configured publication policy. Upload retries require the same durable operation/reconciliation discipline as broadcasts.

Do not invent a `clips.insert` API. Native [YouTube Clips](https://support.google.com/youtube/answer/10332730?hl=en) are source-dependent 5–60-second excerpts with DVR constraints for live sources. [Shorts](https://support.google.com/youtube/answer/15424877?hl=en) can be square or vertical and up to three minutes under the documented date rules; an active copyright claim on a Short over one minute blocks it globally until resolved.

Chat publication time does not reveal the author's exact video playhead. DVR, ads, buffering, typing, and viewer-to-viewer replies prevent a fixed offset from proving which joke caused a response. Treat scene attribution as an estimate with uncertainty. High message volume can mean confusion, spam, or a technical complaint.

Use original-script/editorial assessment and optional direct website “Clip this moment” votes with actual playhead context. Keep first-party votes separate from YouTube API Data. After approved analytics integration, additional candidate ranking can consider scene relevance, participant diversity, duplicate limits, and positive response, while penalizing missing setup, spoilers, harassment, and near-duplicate clips. Do not claim a score is validated without evaluation.

Native [retention data](https://support.google.com/youtube/answer/9314415?hl=en) typically takes one to two days to process. Rewatch spikes can reflect confusion. Use delayed retention and direct feedback to reassess candidates; do not label provisional live reactions as proven audience satisfaction.

## 7. Derived metrics and data retention

The baseline [Developer Policies](https://developers.google.com/youtube/terms/developer-policies) prohibit new/derived metrics from API Data. The [additional derived-metrics policy](https://developers.google.com/youtube/terms/derived-metrics-policy) provides an application/amendment path for accepted audited analytics use cases, including sentiment/comment NLP. Confirm this permission before enabling proprietary YouTube-derived engagement or sentiment scoring. Clearly label accepted custom metrics as Star's estimates, distinct from native YouTube statistics; never infer protected personal characteristics.

Separate raw API chat/metadata, authorized statistics, authored show canon, and first-party feedback. Raw non-statistical API Data generally requires refresh or deletion within 30 days. The accepted amendment permits specified statistical/derived metrics for up to 36 months but leaves comment text and other named metadata under the 30-day rule. Implement revocation/deletion handling. Permanent model training on raw viewer chat is outside this default design.

## 8. Audience, disclosure, voices, and originality

Decide the genuine intended audience during show development. [General-audience animation](https://support.google.com/youtube/answer/9528076?hl=en) is different from child-directed/mixed-audience content; made-for-kids streams lose live chat/replay. Do not select an inaccurate audience flag to retain interaction.

Current [AI disclosure rules](https://support.google.com/youtube/answer/14328491?hl=en) require relevant realistic synthetic/altered content to be disclosed; clearly non-realistic animation generally does not require disclosure by itself. Explain the production openly, including generated music when applicable. Set the documented video `status.containsSyntheticMedia` field when required; do not invent that field on `liveBroadcasts`.

Use original fictional voices or explicitly authorized performers. Maintain consent/license scope for likeness, voice, live improvisation, clips, and distribution. [Impersonation rules](https://support.google.com/youtube/answer/2801947?hl=en) cover AI likeness/voice falsely implying participation, ownership, or endorsement. Disclosure does not override those rules.

[Monetization guidance](https://support.google.com/youtube/answer/1311392?hl=en) allows recurring characters with distinct episodic stories and creative value; interchangeable templates and generic mass production are unsuitable. The [spam policy](https://support.google.com/youtube/answer/2801973?hl=en) separately prohibits flooding with repetitive synthetic content. No audience growth or revenue is established by technical automation.

## 9. Website and session handoff

Provide a stable Watch route with a current-session record, cast, episode archive, accurate live state, and next-session information. Atomically update its broadcast ID after confirming the next session. Do not redirect viewers away from an episode they chose to finish.

The [chat iframe](https://support.google.com/youtube/answer/2524549?hl=en) requires `embed_domain` to match the embedding host and is unavailable on mobile web; provide a YouTube chat/app action. [Live Redirect](https://support.google.com/youtube/answer/10359590?hl=en) requires more than 1,000 subscribers and no Community Guideline strikes, with destination permission for other channels. No public redirect-control endpoint was verified here. A new channel cannot promise seamless migration of all viewers between session IDs.

## 10. Manual end-to-end acceptance — not executed

Run these checks only after the owner has configured the intended channel and authorized its test scope. Record observations and failures; do not mark planned checks as passed.

- Confirm channel identity, eligibility, OAuth refresh, actual quotas, privacy, audience, and disclosure settings.
- Run an unlisted test from approved media; inspect picture, sound, captions, actual latency, health freshness, and the local recording.
- Interrupt encoder/network service; verify recovery preserves the intended session and never duplicates broadcasts.
- Simulate token revocation, terminal policy state, quota exhaustion, ambiguous mutation results, and missing fresh media; verify appropriate stop/fallback behavior.
- Exercise chat reconnects, duplicate delivery, gift updates, ended/disabled chats, unsafe usernames, and late questions.
- Complete an episode/Q&A and session rollover; verify canon, timestamps, archive mapping, mobile chat fallback, and explicit handoff behavior.
- Produce a local highlight; verify setup/payoff, framing, captions, audio rights, and publication state before any public release.
- Confirm derived-metric permission, retention/deletion jobs, and that every displayed metric comes from observed data or an honest empty state.
