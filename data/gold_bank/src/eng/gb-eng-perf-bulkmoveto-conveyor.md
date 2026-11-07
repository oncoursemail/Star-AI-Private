---
id: gb-eng-perf-bulkmoveto-conveyor
category: performance
topics: workspace:BulkMoveTo, CFrame updates, anchored parts, property events, batching
source: original
---
# Request
I animate 400 anchored "ore" parts along conveyor paths by setting `part.CFrame` in a loop every frame and it costs several milliseconds. I heard about `workspace:BulkMoveTo`. How do I use it correctly, and what do I give up?

# Answer
Collect the parts and their target CFrames into two arrays and move them with one `BulkMoveTo` call per frame. Pass `Enum.BulkMoveMode.FireCFrameChanged` so only CFrame change events fire, which is cheaper than the default of firing every property event. Reuse the two arrays every frame so the batch itself does not allocate.

```lua
--!strict
-- ModuleScript: ServerScriptService.ConveyorMover
export type Item = { part: BasePart, distance: number }
export type Path = { origin: CFrame, direction: Vector3, length: number }

local ConveyorMover = {}

local partsBuffer: { BasePart } = {}
local cframesBuffer: { CFrame } = {}

function ConveyorMover.step(items: { Item }, path: Path, speed: number, dt: number): number
	table.clear(partsBuffer)
	table.clear(cframesBuffer)
	local wrapped = 0
	for _, entry in items do
		entry.distance += speed * dt
		if entry.distance > path.length then
			entry.distance -= path.length
			wrapped += 1
		end
		table.insert(partsBuffer, entry.part)
		table.insert(cframesBuffer, path.origin + path.direction * entry.distance)
	end
	workspace:BulkMoveTo(partsBuffer, cframesBuffer, Enum.BulkMoveMode.FireCFrameChanged)
	return wrapped
end

return ConveyorMover
```

- `BulkMoveTo` skips the per-assignment property overhead and updates the parts as one batch; it works best for anchored parts you move every frame.
- With `FireCFrameChanged`, listeners on `Position` or `Orientation` stop firing; if some script relies on those, pass `Enum.BulkMoveMode.FireAllEvents` (the default) instead.
- Purely visual movement like this can also run on each client instead of the server, which removes the replication cost of 400 moving parts entirely.

# Test
```lua
local items = {}
for i = 1, 3 do
	local p = Instance.new("Part")
	p.Anchored = true
	p.Parent = workspace
	items[i] = { part = p, distance = (i - 1) * 4 }
end
local path = { origin = CFrame.new(0, 5, 0), direction = Vector3.new(1, 0, 0), length = 9 }
local wrapped = item.step(items, path, 2, 1)
check("parts moved along the path", items[1].part.Position == Vector3.new(2, 5, 0) and items[2].part.Position == Vector3.new(6, 5, 0))
check("item past the end wraps around", wrapped == 1 and math.abs(items[3].distance - 1) < 1e-9 and items[3].part.Position == Vector3.new(1, 5, 0))
item.step(items, path, 2, 0.5)
check("second step continues", items[1].part.Position == Vector3.new(3, 5, 0))
check("empty list is fine", item.step({}, path, 2, 1) == 0)
```
