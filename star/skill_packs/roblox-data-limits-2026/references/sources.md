# Sources for roblox-data-limits-2026

Official Roblox Creator Documentation (CC-BY-4.0), creator-docs commit 4e795e6 (2026-10-24):
https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits

| Claim in the skill | Section of that page |
|---|---|
| Game server and Open Cloud share a budget; external rate limiting (60 / budget seconds, leaky bucket) | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Access limits", "Control rate limits" |
| Experience budgets 300 + 40/20/2/40 x concurrent users; UpdateAsync uses read and write budgets | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Access limits", "Experience limits" tables |
| Server budgets 60 + 40 x players, list 5 + 2 x players, ordered write/remove 30 + 5 x players; SetRateLimitForRequestType; Studio Run mode static limits | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Server limits" |
| Per-key throughput 25 MB/min read, 4 MB/min write, rounded up per KB | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Throughput limits" |
| 50-character names, 4,194,304-character values; metadata 50 / 250 / 300 | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Data limits", "Metadata limits" |
| Storage 500 MB + 1 MB x lifetime users, compressed latest version only | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Storage limits" |
| Queues of 30 requests; error codes 301-306 | https://create.roblox.com/docs/cloud-services/data-stores/error-codes-and-limits "Limits" |
| Shared budget date 2026-07-29 | docs/research/roblox-2026-20261023.md section 1.6 [C] (DevForum 2026-07-15 announcement) |
| Profile, autosave, BindToClose, UpdateAsync, retry patterns | https://create.roblox.com/docs/cloud-services/data-stores/best-practices |

API names verified with the knowledge service /api-lookup on 2026-10-25 (all found, none deprecated): DataStoreService:SetRateLimitForRequestType, DataStoreService:GetRequestBudgetForRequestType, HttpService:JSONEncode, DataModel:BindToClose, GlobalDataStore:UpdateAsync, DataStoreService:ListDataStoresAsync, OrderedDataStore:GetSortedAsync.
