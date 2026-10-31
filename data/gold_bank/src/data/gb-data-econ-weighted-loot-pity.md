---
id: gb-data-econ-weighted-loot-pity
category: economy-simulation
topics: loot table, weighted random, pity counter, crates, Random
source: original
---
# Request
I'm making crates with Common/Rare/Epic/Legendary drops using weights. I also want a pity system: if you open 50 crates without a Legendary, the next one is guaranteed. How do I implement the roll on the server?

# Answer
Roll on the server with a `Random` object: pick a number in [0, total weight) and walk the table until the running sum passes it. Keep the pity counter in the player's data; once it has reached the limit (that many dry opens in a row), force the Legendary on the next open and reset it, and reset it whenever a Legendary drops naturally.

```lua
--!strict
-- ModuleScript: ServerScriptService.CrateRoller
export type Entry = { id: string, rarity: string, weight: number }
export type PityState = { sinceLegendary: number }

local CrateRoller = {}

function CrateRoller.new(entries: { Entry }, pityLimit: number, rng: Random?)
	local random = rng or Random.new()
	local total = 0
	local legendaries: { Entry } = {}
	for _, entry in entries do
		assert(entry.weight > 0, "weights must be positive")
		total += entry.weight
		if entry.rarity == "Legendary" then
			table.insert(legendaries, entry)
		end
	end
	assert(#legendaries > 0, "pity needs at least one Legendary entry")

	local function pick(list: { Entry }, sum: number): Entry
		local roll = random:NextNumber() * sum
		for _, entry in list do
			roll -= entry.weight
			if roll < 0 then
				return entry
			end
		end
		return list[#list] -- floating point edge: roll landed exactly on the total
	end

	local legendaryTotal = 0
	for _, entry in legendaries do
		legendaryTotal += entry.weight
	end

	local function open(state: PityState): (Entry, boolean)
		if state.sinceLegendary >= pityLimit then
			state.sinceLegendary = 0
			return pick(legendaries, legendaryTotal), true
		end
		local entry = pick(entries, total)
		state.sinceLegendary = if entry.rarity == "Legendary" then 0 else state.sinceLegendary + 1
		return entry, false
	end

	return { open = open, chance = function(id: string): number
		for _, entry in entries do
			if entry.id == id then
				return entry.weight / total
			end
		end
		return 0
	end }
end

return CrateRoller
```

- Charge for the crate before calling `open`, and save `sinceLegendary` with the player's data, or rejoining resets their pity.
- Publish the odds from `chance` in the crate UI; paid random items need visible odds, and `PolicyService` tells you where they are restricted.
- Seeding `Random.new(seed)` is only for tests; in a live server let it seed itself so rolls cannot be predicted.

# Test
```lua
local entries = {
	{ id = "stick", rarity = "Common", weight = 70 },
	{ id = "blade", rarity = "Rare", weight = 25 },
	{ id = "crown", rarity = "Legendary", weight = 5 },
}
local roller = item.new(entries, 50, Random.new(42))
check("chances come from weights", math.abs(roller.chance("crown") - 0.05) < 1e-9 and roller.chance("nope") == 0)

local counts = { stick = 0, blade = 0, crown = 0 }
local free = { sinceLegendary = -1e9 } -- pity effectively off to measure raw odds
for _ = 1, 20000 do
	local entry = roller.open(free)
	counts[entry.id] += 1
	free.sinceLegendary = -1e9
end
check("common drops near 70%", math.abs(counts.stick / 20000 - 0.70) < 0.02)
check("legendary drops near 5%", math.abs(counts.crown / 20000 - 0.05) < 0.01)

local unlucky = item.new({ { id = "stick", rarity = "Common", weight = 1e9 }, { id = "crown", rarity = "Legendary", weight = 1e-9 } }, 50, Random.new(1))
local state = { sinceLegendary = 0 }
local forcedAt = nil
for i = 1, 60 do
	local entry, forced = unlucky.open(state)
	if forced then
		forcedAt = i
		check("pity gives the legendary", entry.id == "crown")
		break
	end
end
check("pity triggers on the open after 50 dry ones", forcedAt == 51 and state.sinceLegendary == 0)
```
