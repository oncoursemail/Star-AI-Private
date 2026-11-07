---
id: gb-src-swapremove-projectiles
category: engineering-algorithm
topics: arrays, swap remove, O(1) removal, table.remove, projectile simulation, iteration
source: adapted
source_id: rbxutil
source_path: modules/table-util/init.luau
source_commit: 31f9120fca021e3dec275b42bc7047d626962082
---
# Request
I simulate a few hundred projectiles in an array and remove expired ones with `table.remove(projectiles, i)` inside the update loop. It gets slow and sometimes skips projectiles. What's the right way to remove from an array while iterating?

# Answer
`table.remove` shifts every later element down (O(n) per removal), and removing while counting upward skips the element that slides into slot `i`. When order does not matter, swap-remove instead: move the last element into slot `i` and drop the end, and iterate backwards so the swapped-in element has already been visited.

```lua
--!strict
export type Projectile = { position: Vector3, velocity: Vector3, life: number }

local Projectiles = {}

function Projectiles.swapRemove<T>(list: { T }, index: number)
	local last = #list
	list[index] = list[last]
	list[last] = nil
end

function Projectiles.step(list: { Projectile }, dt: number): number
	local removed = 0
	for i = #list, 1, -1 do
		local p = list[i]
		p.life -= dt
		if p.life <= 0 then
			Projectiles.swapRemove(list, i)
			removed += 1
		else
			p.position += p.velocity * dt
		end
	end
	return removed
end

return Projectiles
```

- Each removal is O(1): one assignment and one nil, no shifting.
- Walking from the end means the element swapped into slot `i` came from a higher index that was already updated this step, so nothing is skipped or updated twice.
- Use `table.remove` only when order matters (for example a sorted queue).

# Test
```lua
local list = {}
for i = 1, 6 do
	table.insert(list, { position = Vector3.zero, velocity = Vector3.new(1, 0, 0), life = if i % 2 == 0 then 0.5 else 2 })
end
local removed = item.step(list, 1)
check("expired projectiles removed", removed == 3 and #list == 3)
local allAlive = true
for _, p in list do
	if p.life <= 0 then
		allAlive = false
	end
end
check("only live projectiles remain", allAlive)
check("survivors moved exactly once", list[1].position.X == 1 and list[2].position.X == 1 and list[3].position.X == 1)
local single = { 10 }
item.swapRemove(single, 1)
check("removing the only element empties the list", #single == 0)
```
