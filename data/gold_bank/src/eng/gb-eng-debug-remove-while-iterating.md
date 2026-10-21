---
id: gb-eng-debug-remove-while-iterating
category: engineering-debugging
topics: table.remove, iteration, skipped elements, array compaction, projectiles
source: original
---
# Request
Some of my projectiles never get cleaned up when they expire. It seems random. This runs every frame:

```lua
for i, proj in ipairs(projectiles) do
	proj.life -= dt
	if proj.life <= 0 then
		proj.part:Destroy()
		table.remove(projectiles, i)
	end
end
```

# Answer
`table.remove(projectiles, i)` shifts every later element down one slot, but the loop still advances to `i + 1`, so the element that moved into slot `i` is skipped this frame. When two neighbours expire on the same frame the second survives (and its part leaks until a later frame catches it). Compact the array in one pass instead: keep a write index, copy survivors forward, then clear the tail. It never skips and is O(n) rather than O(n^2) for many removals.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ProjectileList
export type Projectile = { life: number, part: BasePart? }

local ProjectileList = {}

function ProjectileList.step(projectiles: { Projectile }, dt: number): number
	local write = 0
	local removed = 0
	for read = 1, #projectiles do
		local proj = projectiles[read]
		proj.life -= dt
		if proj.life > 0 then
			write += 1
			projectiles[write] = proj
		else
			if proj.part then
				proj.part:Destroy()
			end
			removed += 1
		end
	end
	for i = write + 1, #projectiles do
		projectiles[i] = nil
	end
	return removed
end

return ProjectileList
```

- Survivors keep their relative order, which matters if anything else indexes the list by spawn order.
- If order does not matter, the other correct fix is a reverse loop, `for i = #projectiles, 1, -1 do ... table.remove(projectiles, i) end`, because removing at `i` only shifts elements you have already visited.
- Never add or remove keys of a dictionary while a `for k, v in dict` loop is visiting it except for setting the current key to nil; collect changes and apply them after the loop.

# Test
```lua
local list = {}
local parts = {}
for i, life in { 1, 0.1, 0.1, 2, 0.1, 3 } do
	local p = Instance.new("Part")
	p.Parent = workspace
	parts[i] = p
	list[i] = { life = life, part = p }
end
local removed = item.step(list, 0.5)
check("all expired removed, including neighbours", removed == 3 and #list == 3)
check("survivors keep order", list[1].part == parts[1] and list[2].part == parts[4] and list[3].part == parts[6])
check("expired parts destroyed", parts[2].Parent == nil and parts[3].Parent == nil and parts[5].Parent == nil)
check("tail cleared", list[4] == nil and list[5] == nil and list[6] == nil)
item.step(list, 5)
check("everything expires to empty", #list == 0)
check("empty list is fine", item.step({}, 1) == 0)
```
