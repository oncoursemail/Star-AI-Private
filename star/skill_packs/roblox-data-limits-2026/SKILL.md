---
name: roblox-data-limits-2026
description: Current Roblox data store and Open Cloud limits (shared budget since July 2026) - request budgets per experience and per server, per-key throughput, size and storage limits, queues, and how to stay under them.
---
# Data store and Open Cloud limits (as of October 2026)

Game servers and Open Cloud share one request budget per experience (since 2026-07-29): heavy Open Cloud traffic can
throttle in-game saves and the reverse. Rate-limit external tools yourself (a pause of 60 / allowed-requests-per-minute
seconds after each call, or a leaky bucket).

Experience-wide budgets, requests per minute (standard and ordered data stores):
- Read (GetAsync, GetVersionAsync, UpdateAsync's read): 300 + 40 x concurrent users
- Write (SetAsync, IncrementAsync, UpdateAsync's write): 300 + 20 x concurrent users
- List (ListDataStoresAsync, ListKeysAsync, ListVersionsAsync): 300 + 2 x concurrent users
- Remove (RemoveAsync): 300 + 40 x concurrent users
- UpdateAsync spends from both the read and the write budget.

Per-server budgets, requests per minute (adjustable with `DataStoreService:SetRateLimitForRequestType`; check
`DataStoreService:GetRequestBudgetForRequestType(Enum.DataStoreRequestType.X)` before bursts):
- StandardRead, StandardWrite, StandardRemove: 60 + 40 x players; StandardList: 5 + 2 x players
- OrderedRead: 60 + 40 x players; OrderedWrite and OrderedRemove: 30 + 5 x players; OrderedList: 5 + 2 x players
- Studio Run mode has its own lower static limits.

Per key (across all servers, rolling 60 s): reads 25 MB per minute, writes 4 MB per minute; each request is rounded
up to the next KB.

Sizes: data store name, key name and scope at most 50 characters; value at most 4,194,304 characters (measure with
`HttpService:JSONEncode`); user metadata at most 300 characters in total (key 50, value 250).

Storage per experience: 500 MB + 1 MB x lifetime users, counting the compressed latest version of each key only
(old versions and deleted keys do not count). Do not pre-compress values.

Queues: when throttled, requests wait in per-type queues (Set, Ordered set, Get, Ordered get) of 30 requests each;
beyond that they fail with error codes 301-306.

Patterns that stay under the limits:
- One key per player profile, loaded once on join, saved on leave, on `game:BindToClose` and by an autosave every few
  minutes (never every frame or on every coin pickup).
- Use `UpdateAsync` for read-modify-write, `pcall` every call and retry with backoff; never retry in a tight loop.
- Leaderboards: OrderedDataStore writes are the scarcest budget (30 + 5 x players per server); batch them.
