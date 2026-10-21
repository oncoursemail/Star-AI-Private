---
id: gb-data-inv-crafting-atomic
category: server-authoritative-inventory
topics: crafting, recipes, atomic, inventory capacity, rollback
source: original
---
# Request
I'm adding crafting: a recipe takes some items and gives others. My first version removed the ingredients one by one and sometimes players lost ingredients when their inventory was full, or crafted with items they didn't have. How do I make crafting all-or-nothing?

# Answer
Do every check before touching anything: the recipe exists, the batch count is a sane integer, the player has all ingredients for that many crafts, and the outputs will fit after the ingredients are removed. Then apply the changes in one go. With a count-based inventory and a limit on distinct item types, the "will it fit" check is simple arithmetic.

```lua
--!strict
-- ModuleScript: ServerScriptService.Crafting
export type Bag = { counts: { [string]: number }, maxKinds: number }
type Recipe = { inputs: { [string]: number }, outputs: { [string]: number } }
export type Result = "ok" | "unknown recipe" | "bad count" | "missing" | "no space"

local RECIPES: { [string]: Recipe } = {
	plank = { inputs = { log = 1 }, outputs = { plank = 4 } },
	torch = { inputs = { plank = 1, coal = 1 }, outputs = { torch = 4 } },
	iron_pick = { inputs = { plank = 2, iron = 3 }, outputs = { iron_pick = 1 } },
}
local MAX_BATCH = 64

local Crafting = {}

local function kinds(counts: { [string]: number }): number
	local n = 0
	for _ in counts do
		n += 1
	end
	return n
end

function Crafting.craft(bag: Bag, recipeId: unknown, timesArg: unknown): Result
	local recipe = if type(recipeId) == "string" then RECIPES[recipeId] else nil
	if recipe == nil then
		return "unknown recipe"
	end
	if type(timesArg) ~= "number" or timesArg % 1 ~= 0 or timesArg < 1 or timesArg > MAX_BATCH then
		return "bad count"
	end
	local times = timesArg

	-- simulate on a copy; the real bag is only replaced if everything succeeds
	local after: { [string]: number } = {}
	for id, n in bag.counts do
		after[id] = n
	end
	for id, need in recipe.inputs do
		local have = after[id] or 0
		if have < need * times then
			return "missing"
		end
		local left = have - need * times
		after[id] = if left > 0 then left else nil
	end
	for id, made in recipe.outputs do
		after[id] = (after[id] or 0) + made * times
	end
	if kinds(after) > bag.maxKinds then
		return "no space"
	end
	bag.counts = after
	return "ok"
end

return Crafting
```

- Working on a copy and swapping it in at the end is the whole trick: there is no half-crafted state to roll back.
- The batch cap keeps a single request from doing unbounded work and from overflowing counts.
- Fire your "crafted" analytics and UI updates after the swap, never inside the simulation loop.

# Test
```lua
local bag = { counts = { log = 3, coal = 2 }, maxKinds = 4 }
check("crafting planks consumes logs and adds planks", item.craft(bag, "plank", 2) == "ok"
	and bag.counts.log == 1 and bag.counts.plank == 8)
check("missing ingredients change nothing", item.craft(bag, "iron_pick", 1) == "missing" and bag.counts.plank == 8)
check("a batch larger than the ingredients allow is refused whole", item.craft(bag, "torch", 3) == "missing"
	and bag.counts.coal == 2 and bag.counts.plank == 8)
check("a valid batch crafts several at once", item.craft(bag, "torch", 2) == "ok" and bag.counts.torch == 8
	and bag.counts.coal == nil and bag.counts.plank == 6)

local full = { counts = { log = 1, a = 1, b = 1, c = 1 }, maxKinds = 4 }
check("an ingredient used up frees its kind for the output", item.craft(full, "plank", 1) == "ok" and full.counts.plank == 4)
local tight = { counts = { plank = 2, coal = 2, a = 1 }, maxKinds = 3 }
check("no space leaves ingredients untouched", item.craft(tight, "torch", 1) == "no space" and tight.counts.coal == 2 and tight.counts.plank == 2)

check("unknown recipes and bad counts are refused", item.craft(bag, "diamond", 1) == "unknown recipe"
	and item.craft(bag, "plank", 0) == "bad count" and item.craft(bag, "plank", 0 / 0) == "bad count"
	and item.craft(bag, "plank", 1000) == "bad count")
```
