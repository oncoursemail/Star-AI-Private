---
id: gb-data-memorystore-global-cooldown
category: datastore-safety
topics: MemoryStoreService, sorted map, global cooldown, cross-server, UpdateAsync
source: original
---
# Request
Players can buy a "summon world boss" item, and the boss should spawn in only one server, at most once every 10 minutes across the whole game. How do I make a cooldown that every server respects at the same time?

# Answer
Use a MemoryStore sorted map entry per cooldown name and claim it with `UpdateAsync`: the transform refuses while the stored expiry is in the future, otherwise writes a new expiry. MemoryStore updates are atomic across servers, so exactly one server wins each window. Fail closed: if MemoryStore is unreachable, nobody summons.

```lua
--!strict
-- ModuleScript: ServerScriptService.GlobalCooldown
local MemoryStoreService = game:GetService("MemoryStoreService")

local map = MemoryStoreService:GetSortedMap("GlobalCooldowns")

type Claim = { expiresAt: number, jobId: string }

local GlobalCooldown = {}

-- Returns true when this server won the cooldown. Otherwise false and the seconds left (-1 when unknown).
function GlobalCooldown.tryClaim(name: string, seconds: number): (boolean, number)
	local now = DateTime.now().UnixTimestamp
	local jobId: string = game.JobId
	local claimed = false
	local remaining = -1
	local ok = pcall(function()
		map:UpdateAsync(name, function(old: Claim?): Claim?
			if old and old.expiresAt > now then
				claimed, remaining = false, old.expiresAt - now
				return nil
			end
			claimed, remaining = true, 0
			return { expiresAt = now + seconds, jobId = jobId }
		end, seconds + 60)
	end)
	if not ok then
		return false, -1
	end
	return claimed, remaining
end

return GlobalCooldown
```

Usage in the purchase handler:

```lua
--!strict
local ServerScriptService = game:GetService("ServerScriptService")
local GlobalCooldown = require(ServerScriptService.GlobalCooldown)

local function trySummon(spawnBoss: () -> ()): (boolean, string)
	local won, left = GlobalCooldown.tryClaim("WorldBoss", 600)
	if won then
		spawnBoss()
		return true, "The world boss has been summoned!"
	elseif left > 0 then
		return false, string.format("Another server summoned it. Try again in %d:%02d.", left // 60, left % 60)
	end
	return false, "Summoning is unavailable right now."
end

return trySummon
```

- The entry's expiration (`seconds + 60`) lets MemoryStore clean up by itself; the stored `expiresAt` is what decides, so clock drift of a few seconds between servers only shifts the window slightly.
- Charge the item only after `tryClaim` returns true, or refund on failure, so a busy cooldown never eats a purchase.
- `jobId` in the entry tells you which server owns the current boss, handy for a "boss is live in another server, join?" button.

# Test
```lua
game.JobId = "server-A"
local won = item.tryClaim("WorldBoss", 600)
check("first server wins the cooldown", won)

game.JobId = "server-B"
local again, left = item.tryClaim("WorldBoss", 600)
check("another server is refused during the window", not again and left == 600)

__advance(300)
local _, half = item.tryClaim("WorldBoss", 600)
check("remaining time counts down", half == 300)

check("different cooldown names are independent", item.tryClaim("Meteor", 60))

__advance(301)
check("after the window a server can claim again", item.tryClaim("WorldBoss", 600))
check("and the window restarts", not item.tryClaim("WorldBoss", 600))
```
