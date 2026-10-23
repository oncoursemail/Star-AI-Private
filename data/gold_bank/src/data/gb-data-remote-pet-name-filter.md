---
id: gb-data-remote-pet-name-filter
category: remote-security
topics: TextService, FilterStringAsync, user text, pet name, RemoteFunction
source: original
---
# Request
Players can name their pets and the name floats above the pet for everyone. Right now I just set the name the client sends. What do I need to do to filter it properly?

# Answer
Text written by one player and shown to others must go through `TextService:FilterStringAsync` on the server, using the broadcast result. Validate length and type first, rate-limit renames, and fail closed: if filtering errors, keep the old name instead of showing unfiltered text.

```lua
--!strict
-- ModuleScript: ServerScriptService.PetNames
local TextService = game:GetService("TextService")
local Players = game:GetService("Players")

export type Result = "ok" | "invalid" | "cooldown" | "unavailable"

local MAX_LENGTH = 20
local RENAME_COOLDOWN = 10

local PetNames = {}
local lastRename: { [Player]: number } = {}

Players.PlayerRemoving:Connect(function(player: Player)
	lastRename[player] = nil
end)

local function clean(raw: unknown): string?
	if type(raw) ~= "string" or utf8.len(raw) == nil then
		return nil
	end
	local trimmed = string.match(raw, "^%s*(.-)%s*$") or ""
	trimmed = string.gsub(trimmed, "%s+", " ")
	local length = utf8.len(trimmed) or 0
	if length < 1 or length > MAX_LENGTH then
		return nil
	end
	return trimmed
end

local function filterForEveryone(text: string, fromUserId: number): string?
	local ok, filtered = pcall(function()
		local result = TextService:FilterStringAsync(text, fromUserId)
		return result:GetNonChatStringForBroadcastAsync()
	end)
	if ok and type(filtered) == "string" then
		return filtered
	end
	return nil
end

-- pet is a server-owned Model the caller already checked belongs to this player.
function PetNames.rename(player: Player, pet: Model, raw: unknown): Result
	local text = clean(raw)
	if text == nil then
		return "invalid"
	end
	local now = os.clock()
	local last = lastRename[player]
	if last and now - last < RENAME_COOLDOWN then
		return "cooldown"
	end
	lastRename[player] = now
	local filtered = filterForEveryone(text, player.UserId)
	if filtered == nil then
		return "unavailable"
	end
	pet:SetAttribute("PetName", filtered)
	return "ok"
end

return PetNames
```

- Store the raw name in your save data and filter again each time it is shown in a new session: filtering rules change, and a name that passed last year may not today.
- A name that comes back as `####` is still the right result; show it rather than letting the player retry until something slips through.
- Each `FilterStringAsync` is a web call, which is why renames are rate-limited before filtering.

# Test
```lua
local owner = __makePlayer(1, "Owner")
local pet = Instance.new("Model")
pet.Parent = workspace

check("normal names are filtered and applied", item.rename(owner, pet, "  Mr   Fluffy ") == "ok" and pet:GetAttribute("PetName") == "Mr Fluffy")
check("renames are rate limited", item.rename(owner, pet, "Rex") == "cooldown" and pet:GetAttribute("PetName") == "Mr Fluffy")

__advance(11)
check("filtered words are hidden for everyone", item.rename(owner, pet, "Badword") == "ok" and pet:GetAttribute("PetName") == "#######")

__advance(11)
check("too long, empty and non-string names are invalid", item.rename(owner, pet, string.rep("a", 21)) == "invalid"
	and item.rename(owner, pet, "    ") == "invalid" and item.rename(owner, pet, 123) == "invalid")

local TextService = game:GetService("TextService")
TextService.FilterStringAsync = function()
	error("HTTP 500")
end
check("filter outage fails closed", item.rename(owner, pet, "Rex") == "unavailable" and pet:GetAttribute("PetName") == "#######")
```
