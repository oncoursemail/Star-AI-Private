---
id: gb-world-combat-raycast-blade
category: combat-hitbox
topics: raycast hitbox, sword, attachments, Heartbeat, fast swings
source: original
---
# Request
My greatsword swings so fast that a box hitbox checked every frame skips right past enemies between frames. How do raycast hitboxes for swords work and can you write one?

# Answer
Put several attachments along the blade. While the swing is active, every frame cast a ray from each attachment's previous world position to its current one: the rays sweep the exact path the blade travelled, so nothing between frames is skipped. Each humanoid is reported once per activation.

```lua
--!strict
-- ModuleScript: ServerScriptService.BladeCaster
local RunService = game:GetService("RunService")

export type Caster = {
	begin: () -> (),
	finish: () -> (),
}

local BladeCaster = {}

function BladeCaster.new(
	blade: BasePart,
	ignore: { Instance },
	onHit: (humanoid: Humanoid, part: BasePart, position: Vector3) -> ()
): Caster
	local points: { Attachment } = {}
	for _, child in blade:GetChildren() do
		if child:IsA("Attachment") and child.Name == "DmgPoint" then
			table.insert(points, child)
		end
	end
	assert(#points > 0, "add DmgPoint attachments along the blade")

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = ignore

	local previous: { [Attachment]: Vector3 } = {}
	local hit: { [Humanoid]: boolean } = {}
	local connection: RBXScriptConnection? = nil

	local function worldPoint(point: Attachment): Vector3
		return blade.CFrame:PointToWorldSpace(point.Position)
	end

	local function step()
		for _, point in points do
			local current = worldPoint(point)
			local last = previous[point]
			previous[point] = current
			if last and last ~= current then
				local result = workspace:Raycast(last, current - last, params)
				local model = if result then result.Instance:FindFirstAncestorOfClass("Model") else nil
				local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
				if result and humanoid and humanoid.Health > 0 and not hit[humanoid] then
					hit[humanoid] = true
					onHit(humanoid, result.Instance, result.Position)
				end
			end
		end
	end

	local function finish()
		if connection then
			connection:Disconnect()
			connection = nil
		end
	end

	return {
		begin = function()
			finish()
			table.clear(hit)
			for _, point in points do
				previous[point] = worldPoint(point)
			end
			connection = RunService.Heartbeat:Connect(step)
		end,
		finish = finish,
	}
end

return BladeCaster
```

- Call `begin` when the active frames start (a "HitStart" marker) and `finish` at "HitEnd"; outside that window no rays are cast.
- Three to five points spread from guard to tip are enough; more points only matter for very wide blades.
- Positions are taken from the blade's CFrame, so this works on the server for NPCs; for player weapons cast on the client for responsiveness and validate the claimed hit on the server.

# Test
```lua
local player = __makePlayer(43, "Swordsman")
local character = __makeCharacter(player, Vector3.new(0, 3, 10))
local blade = Instance.new("Part")
blade.Size = Vector3.new(0.5, 4, 0.5)
blade.CFrame = CFrame.new(-6, 3, -3)
blade.Parent = workspace
for _, y in { 0, 1.5 } do
	local point = Instance.new("Attachment")
	point.Name = "DmgPoint"
	point.Position = Vector3.new(0, y, 0)
	point.Parent = blade
end
local enemy = __buildRig(Vector3.new(0, 3, -3))
enemy.Parent = workspace
local hits = {}
local caster = item.new(blade, { character, blade }, function(humanoid)
	table.insert(hits, humanoid)
end)

caster.begin()
blade.CFrame = CFrame.new(6, 3, -3)
__frames(1)
check("fast sweep through the enemy registers", #hits == 1 and hits[1] == enemy.Humanoid)
blade.CFrame = CFrame.new(-6, 3, -3)
__frames(1)
check("same activation does not hit twice", #hits == 1)
caster.finish()
blade.CFrame = CFrame.new(6, 3, -3)
__frames(1)
check("no rays after finish", #hits == 1)
caster.begin()
blade.CFrame = CFrame.new(-6, 3, -3)
__frames(1)
check("a new swing can hit again", #hits == 2)
caster.finish()
check("blade without points is rejected", not pcall(item.new, Instance.new("Part"), {}, function() end))
```
