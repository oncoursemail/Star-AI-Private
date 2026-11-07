---
id: gb-data-inv-consumable-use
category: server-authoritative-inventory
topics: consumables, potion, cooldown, heal, inventory count
source: original
---
# Request
I have health potions in my inventory. The client plays the drink animation and then fires `UsePotion:FireServer(healAmount)`. What's the correct server-side flow for using a consumable?

# Answer
The client only says which item it wants to use. The server checks the player owns one, the item is a consumable, its cooldown group is ready and the character is alive, then removes one and applies the effect defined on the server. The heal amount never comes from the client.

```lua
--!strict
-- ModuleScript: ServerScriptService.Consumables
local Players = game:GetService("Players")

export type Bag = { [string]: number }
type Effect = { heal: number, group: string, cooldown: number }
export type Result = "ok" | "unknown" | "none left" | "cooldown" | "dead"

local EFFECTS: { [string]: Effect } = {
	small_potion = { heal = 25, group = "potion", cooldown = 5 },
	big_potion = { heal = 60, group = "potion", cooldown = 5 },
	apple = { heal = 10, group = "food", cooldown = 2 },
}

local Consumables = {}
local readyAt: { [Player]: { [string]: number } } = {}

Players.PlayerRemoving:Connect(function(player: Player)
	readyAt[player] = nil
end)

function Consumables.use(player: Player, bag: Bag, itemId: unknown): Result
	local effect = if type(itemId) == "string" then EFFECTS[itemId] else nil
	if effect == nil then
		return "unknown"
	end
	local id = itemId :: string
	if (bag[id] or 0) < 1 then
		return "none left"
	end
	local timers = readyAt[player] or {}
	readyAt[player] = timers
	local now = os.clock()
	if (timers[effect.group] or 0) > now then
		return "cooldown"
	end
	local character = player.Character
	local humanoid: Humanoid? = if character then character:FindFirstChildOfClass("Humanoid") else nil
	if humanoid == nil or humanoid.Health <= 0 then
		return "dead"
	end
	bag[id] -= 1
	if bag[id] == 0 then
		bag[id] = nil
	end
	timers[effect.group] = now + effect.cooldown
	humanoid.Health = math.min(humanoid.MaxHealth, humanoid.Health + effect.heal)
	return "ok"
end

return Consumables
```

- Cooldown groups stop players chaining a small and a big potion back to back; food and potions still stack because they are separate groups.
- Refusing at full health is a design choice; this version allows it, which wastes the potion but cannot be abused.
- The client can still play the drink animation instantly as a prediction and show the server's result when it arrives.

# Test
```lua
local p = __makePlayer(1, "Drinker")
local character = __makeCharacter(p)
local humanoid = character.Humanoid
humanoid.Health = 30
local bag = { small_potion = 2, big_potion = 1, apple = 1 }

check("using a potion heals the server amount and consumes one", item.use(p, bag, "small_potion") == "ok"
	and humanoid.Health == 55 and bag.small_potion == 1)
check("same cooldown group is blocked", item.use(p, bag, "big_potion") == "cooldown" and bag.big_potion == 1)
check("a different group is independent", item.use(p, bag, "apple") == "ok" and humanoid.Health == 65 and bag.apple == nil)
check("items you do not have cannot be used", item.use(p, bag, "apple") == "none left")
__advance(5.1)
check("heal is capped at max health", item.use(p, bag, "big_potion") == "ok" and humanoid.Health == 100 and bag.big_potion == nil)
check("unknown items and numbers are refused", item.use(p, bag, "elixir") == "unknown" and item.use(p, bag, 500) == "unknown")
humanoid.Health = 0
__advance(5.1)
check("dead players cannot drink", item.use(p, bag, "small_potion") == "dead" and bag.small_potion == 1)
```
