---
id: gb-data-docs-update-set-increment
category: docs-question
topics: UpdateAsync, SetAsync, IncrementAsync, DataStore, choosing methods
source: original
---
# Request
What is the actual difference between SetAsync, UpdateAsync and IncrementAsync, and how do I pick one?

# Answer
`SetAsync` overwrites the key with your value without looking at what is there, so it is only safe when this server is the sole writer (a session-locked profile). `UpdateAsync` hands your function the current stored value and writes what you return, retrying your function if another server wrote in between; return `nil` to cancel. It is the choice for any read-modify-write. `IncrementAsync` atomically adds an integer to a numeric key and returns the new total, ideal for counters shared by many servers.

```lua
--!strict
local DataStoreService = game:GetService("DataStoreService")

local profiles = DataStoreService:GetDataStore("Profiles")
local stats = DataStoreService:GetDataStore("GlobalStats")
local guilds = DataStoreService:GetDataStore("Guilds")

type Guild = { members: { number } }

local Examples = {}

-- SetAsync: this server owns the profile (session lock), so a blind overwrite is fine.
function Examples.saveProfile(userId: number, profile: { [string]: any }): boolean
	return (pcall(function()
		profiles:SetAsync("user_" .. userId, profile, { userId })
	end))
end

-- IncrementAsync: many servers add to one number; returns the new total.
function Examples.countBossKill(): number?
	local ok, total = pcall(function()
		return stats:IncrementAsync("BossKills", 1)
	end)
	return if ok then total else nil
end

-- UpdateAsync: read-modify-write of a shared record, with a rule that can refuse the change.
function Examples.joinGuild(guildId: string, userId: number, maxMembers: number): boolean
	local joined = false
	local ok = pcall(function()
		guilds:UpdateAsync(guildId, function(guild: Guild?): Guild?
			local record: Guild = guild or { members = {} }
			if #record.members >= maxMembers or table.find(record.members, userId) then
				joined = false
				return nil -- cancel: nothing is written
			end
			table.insert(record.members, userId)
			joined = true
			return record
		end)
	end)
	return ok and joined
end

return Examples
```

- `GetAsync` followed by `SetAsync` on a shared key is the classic lost-update bug; that pattern is what `UpdateAsync` exists to replace.
- The `UpdateAsync` function may run more than once, so it must not have side effects beyond computing the new value (set flags like `joined`, act on them after).
- All three count against the same write budget and per-key limit; `IncrementAsync` does not bypass throttling, it only removes the race.

# Test
```lua
local ds = game:GetService("DataStoreService")
check("profile save works", item.saveProfile(1, { coins = 5 }) and ds:GetDataStore("Profiles"):GetAsync("user_1").coins == 5)
item.countBossKill()
check("increments add up and return the total", item.countBossKill() == 2)
check("joining a guild with room works", item.joinGuild("g1", 10, 2) and item.joinGuild("g1", 11, 2))
check("a full guild refuses without writing", not item.joinGuild("g1", 12, 2)
	and #ds:GetDataStore("Guilds"):GetAsync("g1").members == 2)
check("joining twice is refused", not item.joinGuild("g1", 10, 5))
ds.__failNext = 1
check("store errors are reported as failure", not item.joinGuild("g2", 1, 5))
```
