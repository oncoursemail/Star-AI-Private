---
id: gb-data-econ-gamepass-cache
category: economy-simulation
topics: game pass, UserOwnsGamePassAsync, cache, PromptGamePassPurchaseFinished, perks
source: original
---
# Request
I check `UserOwnsGamePassAsync` every time a player touches a VIP door and sometimes it errors or is slow. Also players who buy the pass in-game don't get the perk until they rejoin. How should I handle game pass ownership?

# Answer
Check ownership once per player per pass, in `pcall`, and cache the answer; a failed check is not cached so it is tried again. Listen to `PromptGamePassPurchaseFinished` to mark the pass owned and apply the perk the moment it is bought, and clear the cache when the player leaves.

```lua
--!strict
-- ModuleScript: ServerScriptService.GamePasses
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

local cache: { [Player]: { [number]: boolean } } = {}
local perks: { [number]: (Player) -> () } = {}

local GamePasses = {}

-- nil once the player has left, so a late call cannot re-create the entry PlayerRemoving cleared.
local function cacheFor(player: Player): { [number]: boolean }?
	if player.Parent ~= Players then
		return nil
	end
	local mine = cache[player]
	if mine == nil then
		mine = {}
		cache[player] = mine
	end
	return mine
end

function GamePasses.owns(player: Player, passId: number): boolean
	local mine = cacheFor(player)
	if mine == nil then
		return false
	end
	local known = mine[passId]
	if known ~= nil then
		return known
	end
	local ok, owned = pcall(function()
		return MarketplaceService:UserOwnsGamePassAsync(player.UserId, passId)
	end)
	if not ok then
		return false -- treat as not owned for now, ask again next time
	end
	mine[passId] = owned == true
	return mine[passId]
end

-- perk runs on join for owners and immediately after an in-game purchase.
function GamePasses.onOwned(passId: number, perk: (Player) -> ())
	perks[passId] = perk
	for _, player in Players:GetPlayers() do
		if GamePasses.owns(player, passId) then
			task.spawn(perk, player)
		end
	end
end

local function applyAll(player: Player)
	for passId, perk in perks do
		if GamePasses.owns(player, passId) then
			task.spawn(perk, player)
		end
	end
end

MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player: Player, passId: number, purchased: boolean)
	if not purchased then
		return
	end
	local mine = cacheFor(player)
	if mine == nil then
		return
	end
	mine[passId] = true
	local perk = perks[passId]
	if perk then
		task.spawn(perk, player)
	end
end)

Players.PlayerAdded:Connect(applyAll)
Players.PlayerRemoving:Connect(function(player: Player)
	cache[player] = nil
end)

return GamePasses
```

Usage: `GamePasses.onOwned(script:GetAttribute("VipPassId"), function(player) player:SetAttribute("VIP", true) end)`, and the VIP door checks `GamePasses.owns(player, vipPassId)`.

- `purchased == true` in `PromptGamePassPurchaseFinished` comes from Roblox on the server, so it is safe to trust; a client cannot fire it.
- Perks must be safe to apply twice (setting an attribute, giving a tool only if missing), because a join and a purchase can both trigger them.
- Never prompt the purchase from server code in response to an untrusted remote without rate limiting; prompting from the client with `PromptGamePassPurchase` is normal.

# Test
```lua
local mps = game:GetService("MarketplaceService")
mps.__owned[1] = { [77] = true }
local owner = __makePlayer(1, "Owner")
local buyer = __makePlayer(2, "Buyer")
local applied = {}
item.onOwned(77, function(player)
	applied[player] = (applied[player] or 0) + 1
end)
check("existing owners get the perk when it is registered", applied[owner] == 1 and applied[buyer] == nil)
check("ownership is cached", item.owns(owner, 77))
mps.__owned[1] = nil
check("cached answer survives later checks", item.owns(owner, 77))

check("non-owners are refused", not item.owns(buyer, 77))
mps.PromptGamePassPurchaseFinished:Fire(buyer, 77, true)
check("buying in-game applies the perk immediately", applied[buyer] == 1 and item.owns(buyer, 77))
mps.PromptGamePassPurchaseFinished:Fire(buyer, 88, false)
check("cancelled prompts change nothing", not item.owns(buyer, 88))

mps.__owned[3] = { [77] = true }
local joiner = __makePlayer(3, "Joiner")
check("owners joining later get the perk", applied[joiner] == 1)
__removePlayer(joiner)
check("calls after a player left answer false without caching them again", not item.owns(joiner, 77))
```
