---
id: gb-src-gamepass-ownership-check
category: economy-simulation
topics: MarketplaceService, game pass, UserOwnsGamePassAsync, PromptGamePassPurchaseFinished, server authority
source: adapted
source_id: creator-docs
source_path: content/en-us/production/monetization/passes.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
I have a VIP game pass that gives double walk speed. How do I give the perk on join to owners and also right after someone buys it in-game?

# Answer
Check ownership on the server with `UserOwnsGamePassAsync` (it can fail, so wrap it in `pcall`) when a player joins, and listen to `PromptGamePassPurchaseFinished` for in-game purchases. Store the result as an attribute and apply it on every spawn so the perk survives respawns.

```lua
--!strict
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

local VIP_PASS_ID = 1234567
local VIP_WALK_SPEED = 32

local function applyPerk(character: Model?)
	local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
	if humanoid then
		humanoid.WalkSpeed = VIP_WALK_SPEED
	end
end

local function grantVip(player: Player)
	player:SetAttribute("IsVip", true)
	applyPerk(player.Character)
end

local function onPlayerAdded(player: Player)
	player.CharacterAdded:Connect(function(character: Model)
		if player:GetAttribute("IsVip") then
			applyPerk(character)
		end
	end)

	local ok, ownsPass = pcall(function()
		return MarketplaceService:UserOwnsGamePassAsync(player.UserId, VIP_PASS_ID)
	end)
	if not ok then
		warn("Pass check failed for", player.Name, ownsPass)
	elseif ownsPass then
		grantVip(player)
	end
end

MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player: Player, passId: number, purchased: boolean)
	if purchased and passId == VIP_PASS_ID then
		grantVip(player)
	end
end)

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end
```

- Ownership is decided on the server; the client only shows the prompt with `MarketplaceService:PromptGamePassPurchase(player, VIP_PASS_ID)`.
- `CharacterAdded` re-applies the perk after each respawn because the Humanoid is new; the `IsVip` attribute also lets client UI show the perk.
- The loop over existing players covers anyone who joined before the script connected.

# Test
```lua
local MarketplaceService = game:GetService("MarketplaceService")
MarketplaceService.__owned[10] = { [1234567] = true }
local owner = __makePlayer(10, "Owner")
local other = __makePlayer(11, "Other")
__advance(0.1)
local ownerHumanoid = __makeCharacter(owner):FindFirstChildOfClass("Humanoid")
local otherHumanoid = __makeCharacter(other):FindFirstChildOfClass("Humanoid")
__advance(0.1)
check("owner flagged", owner:GetAttribute("IsVip") == true)
check("owner gets speed on spawn", ownerHumanoid.WalkSpeed == 32)
check("non-owner unchanged", other:GetAttribute("IsVip") == nil and otherHumanoid.WalkSpeed ~= 32)
MarketplaceService.PromptGamePassPurchaseFinished:Fire(other, 999, true)
check("other pass id ignored", other:GetAttribute("IsVip") == nil)
MarketplaceService.PromptGamePassPurchaseFinished:Fire(other, 1234567, true)
check("in-game purchase grants immediately", otherHumanoid.WalkSpeed == 32)
```
