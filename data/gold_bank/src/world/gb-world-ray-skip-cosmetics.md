---
id: gb-world-ray-skip-cosmetics
category: world-raycast
topics: raycast filter, accessories, invisible parts, recast loop, hit detection
source: original
---
# Request
My gun's raycast keeps hitting hats, hair and invisible barrier parts instead of the player or the wall behind them. I can't put every accessory in the filter list before shooting because players equip things all the time. What's the usual fix?

# Answer
Cast, and if the hit is something bullets should pass through (an accessory handle, or a nearly transparent or non-collidable part that is not a character's body), add it to the exclude list and cast again from the same origin. A small iteration cap keeps the cost bounded. A shot through a hat goes on to hit the head behind it, so it still counts on the player.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ShotRay
local ShotRay = {}

local MAX_PASSES = 6

function ShotRay.passesThrough(part: BasePart): boolean
	if part:FindFirstAncestorOfClass("Accessory") then
		return true
	end
	-- Body parts always count: the Humanoid turns CanCollide off on R15 arms and legs.
	local model = part:FindFirstAncestorOfClass("Model")
	if model and model:FindFirstChildOfClass("Humanoid") then
		return false
	end
	return part.Transparency >= 0.95 or not part.CanCollide
end

function ShotRay.cast(origin: Vector3, direction: Vector3, ignore: { Instance }): RaycastResult?
	local exclude = table.clone(ignore)
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	for _ = 1, MAX_PASSES do
		params.FilterDescendantsInstances = exclude
		local result = workspace:Raycast(origin, direction, params)
		if result == nil or not ShotRay.passesThrough(result.Instance) then
			return result
		end
		table.insert(exclude, result.Instance)
	end
	return nil
end

return ShotRay
```

- Recasting from the same origin keeps distances and positions exact; only the blocking cosmetic is removed from consideration.
- `FilterDescendantsInstances` is copied when assigned, so the table must be reassigned after each insert for the new exclusion to apply.
- The cap stops a shot through a forest of invisible parts from costing dozens of casts; six passes covers a hat, hair and a barrier with room to spare.
- Collision groups are the zero-cost alternative for barriers you control: put them in a group and set `params.CollisionGroup` so the ray never sees them.

# Test
```lua
local player = __makePlayer(103, "Hatted")
local character = __makeCharacter(player, Vector3.new(0, 3, -20))
local hat = Instance.new("Accessory")
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Size = Vector3.new(3, 1, 3)
handle.Position = Vector3.new(0, 3, -18)
handle.Parent = hat
hat.Parent = character
local barrier = Instance.new("Part")
barrier.Anchored = true
barrier.Transparency = 1
barrier.Size = Vector3.new(20, 20, 1)
barrier.Position = Vector3.new(0, 5, -10)
barrier.Parent = workspace
local shooter = __buildRig(Vector3.new(0, 3, 0))
shooter.Parent = workspace

local ignore = { shooter }
local result = item.cast(Vector3.new(0, 3, 0), Vector3.new(0, 0, -100), ignore)
check("skips the invisible barrier and the hat", result ~= nil and result.Instance == character.HumanoidRootPart)
check("barrier and accessories pass through", item.passesThrough(barrier) and item.passesThrough(handle))
check("solid body parts do not", not item.passesThrough(character.Head))
character.RightHand.CanCollide = false
check("non-collidable limbs still count as hits", not item.passesThrough(character.RightHand))
barrier.Transparency = 0
local blocked = item.cast(Vector3.new(0, 3, 0), Vector3.new(0, 0, -100), { shooter })
check("a visible wall still blocks", blocked ~= nil and blocked.Instance == barrier)
check("caller's ignore list is not modified", #ignore == 1 and ignore[1] == shooter)
```
