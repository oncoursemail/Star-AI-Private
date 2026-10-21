---
id: gb-world-vfx-chain-lightning
category: vfx-beam-trail
topics: Beam, chain lightning, GetPartBoundsInRadius, attachments, Debris
source: original
---
# Request
I want a chain lightning ability: it hits the closest enemy, then jumps to the closest enemy from there, up to 4 jumps, never hitting the same one twice, and draws a lightning beam for each jump. How should I split the target picking and the beams?

# Answer
Target picking is gameplay, so it runs on the server: a loop that searches around the current position, picks the nearest living humanoid not already hit, and moves on from there. Drawing is a separate function that creates one Beam per hop between the targets' root attachments and cleans them up shortly after; the server sends the chain to clients and they call it.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ChainLightning
local Debris = game:GetService("Debris")

local ChainLightning = {}

function ChainLightning.findChain(origin: Vector3, maxJumps: number, jumpRange: number, ignore: { Instance }): { Model }
	local params = OverlapParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = ignore
	local chain: { Model } = {}
	local alreadyHit: { [Model]: boolean } = {}
	local current = origin

	for _ = 1, maxJumps do
		local best, bestDistance, bestPosition = nil, math.huge, nil
		for _, part in workspace:GetPartBoundsInRadius(current, jumpRange, params) do
			local model = part:FindFirstAncestorOfClass("Model")
			local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
			local root = if model then model:FindFirstChild("HumanoidRootPart") else nil
			if humanoid and root and humanoid.Health > 0 and not alreadyHit[model] then
				local distance = (root.Position - current).Magnitude
				if distance < bestDistance then
					best, bestDistance, bestPosition = model, distance, root.Position
				end
			end
		end
		if best == nil then
			break
		end
		alreadyHit[best] = true
		table.insert(chain, best)
		current = bestPosition
	end
	return chain
end

function ChainLightning.drawChain(start: Attachment, chain: { Model }, template: Beam, lifetime: number): { Beam }
	local beams: { Beam } = {}
	local previous = start
	for _, model in chain do
		local root = model:FindFirstChild("HumanoidRootPart")
		local target = if root then root:FindFirstChild("RootAttachment") else nil
		if target and target:IsA("Attachment") then
			local beam = template:Clone()
			beam.Attachment0 = previous
			beam.Attachment1 = target
			beam.CurveSize0 = math.random(-3, 3)
			beam.CurveSize1 = math.random(-3, 3)
			beam.Parent = target
			Debris:AddItem(beam, lifetime)
			beams[#beams + 1] = beam
			previous = target
		end
	end
	return beams
end

return ChainLightning
```

- Each hop searches around the last target, not the caster, which is what makes the chain travel across a group.
- `alreadyHit` is per cast, so the bolt can never bounce back and forth between two enemies.
- Beams follow their attachments automatically, so a jumping target keeps the bolt attached without per-frame code; random `CurveSize` values give each hop a different arc.
- Apply damage on the server from `findChain`'s result (for example 30, then 80% per jump) and send the model list to clients with FireAllClients for `drawChain`.

# Test
```lua
local function dummy(x)
	local rig = __buildRig(Vector3.new(x, 3, 0))
	local att = Instance.new("Attachment")
	att.Name = "RootAttachment"
	att.Parent = rig.HumanoidRootPart
	rig.Parent = workspace
	return rig
end
local caster = dummy(0)
local a, b, c = dummy(10), dummy(20), dummy(30)
local far = dummy(80)

local chain = item.findChain(Vector3.new(0, 3, 0), 4, 12, { caster })
check("chain hops nearest first", chain[1] == a and chain[2] == b and chain[3] == c)
check("stops when nothing is in range", #chain == 3 and table.find(chain, far) == nil)
b.Humanoid.Health = 0
local broken = item.findChain(Vector3.new(0, 3, 0), 4, 12, { caster })
check("dead targets break the chain", #broken == 1 and broken[1] == a)
check("max jumps respected", #item.findChain(Vector3.new(0, 3, 0), 1, 12, { caster }) == 1)

local template = Instance.new("Beam")
local beams = item.drawChain(caster.HumanoidRootPart.RootAttachment, chain, template, 0.3)
check("one beam per hop linking attachments", #beams == 3 and beams[2].Attachment0 == a.HumanoidRootPart.RootAttachment)
__advance(0.4)
check("beams cleaned up after their lifetime", beams[1].Parent == nil and beams[3].Parent == nil)
```
