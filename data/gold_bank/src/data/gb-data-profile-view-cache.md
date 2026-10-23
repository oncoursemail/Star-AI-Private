---
id: gb-data-profile-view-cache
category: datastore-safety
topics: DataStore, read cache, TTL, profile viewer, request budget
source: original
---
# Request
My lobby has a "view profile" button that shows any player's stats, including offline friends. Each click does a GetAsync and people spam it, burning my read budget. How can I cache these reads?

# Answer
Put a small read-through cache in front of the store: keep each loaded profile summary with a timestamp, serve it from memory while it is fresh, and share one in-flight request between callers asking for the same user at once. Only a public summary is cached and returned, never the whole save.

```lua
--!strict
-- ModuleScript: ServerScriptService.ProfileViews
local DataStoreService = game:GetService("DataStoreService")

local store = DataStoreService:GetDataStore("PlayerData")
local TTL = 120
local MAX_ENTRIES = 500

export type Summary = { level: number, wins: number, title: string }
type Entry = { summary: Summary?, fetched: number }

local cache: { [number]: Entry } = {}
local count = 0
local inFlight: { [number]: { thread } } = {}

local ProfileViews = {}

local function summarize(saved: any): Summary?
	if type(saved) ~= "table" then
		return nil
	end
	return {
		level = tonumber(saved.level) or 1,
		wins = tonumber(saved.wins) or 0,
		title = if type(saved.title) == "string" then saved.title else "",
	}
end

local function remember(userId: number, summary: Summary?)
	if cache[userId] == nil then
		if count >= MAX_ENTRIES then
			table.clear(cache) -- simple and bounded; a lobby rarely needs more than a few hundred
			count = 0
		end
		count += 1
	end
	cache[userId] = { summary = summary, fetched = os.clock() }
end

-- Returns the summary (nil for players with no save) and whether the lookup succeeded.
function ProfileViews.get(userId: number): (Summary?, boolean)
	local entry = cache[userId]
	if entry and os.clock() - entry.fetched < TTL then
		return entry.summary, true
	end
	local waiting = inFlight[userId]
	if waiting then
		table.insert(waiting, coroutine.running())
		return coroutine.yield()
	end
	inFlight[userId] = {}
	local ok, saved = pcall(function()
		return store:GetAsync("player_" .. userId)
	end)
	local summary = if ok then summarize(saved) else nil
	if ok then
		remember(userId, summary)
	end
	local waiters = inFlight[userId]
	inFlight[userId] = nil
	for _, thread in waiters do
		task.spawn(thread, summary, ok)
	end
	return summary, ok
end

return ProfileViews
```

- Failures are not cached, so a brief outage does not show "no profile" for two minutes.
- Callers who arrive while a read is running wait for that read instead of starting their own, which is what stops a spam-clicked button from multiplying requests.
- For players in the same server, read the live session data instead; the cache is for everyone else, and two minutes of staleness is fine for a profile card.

# Test
```lua
local ds = game:GetService("DataStoreService")
ds:GetDataStore("PlayerData"):SetAsync("player_5", { level = 12, wins = 40, title = "Champion", coins = 999999 })
local before = ds.__calls
local summary, ok = item.get(5)
check("first view loads the summary", ok and summary ~= nil and summary.level == 12 and summary.title == "Champion")
check("private fields are not exposed", (summary :: any).coins == nil)
item.get(5)
item.get(5)
check("repeat views inside the TTL hit the cache", ds.__calls == before + 1)
__advance(121)
item.get(5)
check("after the TTL the profile is read again", ds.__calls == before + 2)

local none, okNone = item.get(6)
check("players without a save return nil but succeed", none == nil and okNone)
ds.__failNext = 1
local _, okFail = item.get(7)
check("failures are reported", not okFail)
ds:GetDataStore("PlayerData"):SetAsync("player_7", { level = 3 })
local retry = item.get(7)
check("failures are not cached", retry ~= nil and retry.level == 3)
```
