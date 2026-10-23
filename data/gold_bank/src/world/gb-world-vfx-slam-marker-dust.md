---
id: gb-world-vfx-slam-marker-dust
category: vfx-particles
topics: animation marker, marker parameter, ground slam, ParticleEmitter, raycast
source: original
---
# Request
I have a ground slam animation with an "Impact" marker. I want a dust ring to burst on the floor exactly at the impact, and I'd like the light and heavy versions of the slam to use the same marker but different dust amounts. Is that possible?

# Answer
Yes: a marker can carry a parameter string, and `GetMarkerReachedSignal` passes it to your handler. Put "0.5" on the light slam's marker and "2" on the heavy one, then scale the emit counts by it. A short ray from the root finds the floor so the dust sits on the ground even on slopes and stairs.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SlamDust
local Debris = game:GetService("Debris")

local SlamDust = {}

function SlamDust.attach(track: AnimationTrack, character: Model, template: Attachment): RBXScriptConnection
	local root = character:FindFirstChild("HumanoidRootPart")
	assert(root and root:IsA("BasePart"), "character needs a HumanoidRootPart")
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }

	return track:GetMarkerReachedSignal("Impact"):Connect(function(parameter: string?)
		local ground = workspace:Raycast(root.Position, Vector3.new(0, -8, 0), params)
		if ground == nil then
			return
		end
		local strength = math.clamp(tonumber(parameter) or 1, 0.1, 4)
		local dust = template:Clone()
		dust.Parent = workspace.Terrain
		dust.WorldPosition = ground.Position
		for _, emitter in dust:GetChildren() do
			if emitter:IsA("ParticleEmitter") then
				local base = emitter:GetAttribute("EmitCount")
				emitter:Emit(math.max(1, math.round((if type(base) == "number" then base else 12) * strength)))
			end
		end
		Debris:AddItem(dust, 2)
	end)
end

return SlamDust
```

- Marker parameters are typed in the Animation Editor's marker properties; they arrive as strings, hence `tonumber` with a default.
- The strength is clamped so a typo like "200" in a marker cannot flood the screen with particles.
- If the slam happens in mid-air (no ground within 8 studs) nothing spawns, which avoids dust floating under a jumping character.

# Test
```lua
local terrain = Instance.new("Terrain")
terrain.Name = "Terrain"
terrain.CanQuery = false
terrain.Parent = workspace
```
```lua
local floor = Instance.new("Part")
floor.Anchored = true
floor.Size = Vector3.new(50, 1, 50)
floor.Position = Vector3.new(0, 0, 0)
floor.Parent = workspace
local player = __makePlayer(15, "Slammer")
local character = __makeCharacter(player, Vector3.new(0, 3, 0))
local template = Instance.new("Attachment")
template.Name = "Dust"
local ring = Instance.new("ParticleEmitter")
ring.Name = "Ring"
ring:SetAttribute("EmitCount", 10)
ring.Parent = template
local track = character.Humanoid.Animator:LoadAnimation(Instance.new("Animation"))
local connection = item.attach(track, character, template)
local marker = track:GetMarkerReachedSignal("Impact")

marker:Fire("2")
local dust = workspace.Terrain:FindFirstChild("Dust")
check("dust placed on the floor surface", dust ~= nil and math.abs(dust.WorldPosition.Y - 0.5) < 1e-6)
check("parameter scales the emit count", dust.Ring.__emitted == 20)
dust:Destroy()
marker:Fire("200")
check("strength is clamped", workspace.Terrain.Dust.Ring.__emitted == 40)
workspace.Terrain.Dust:Destroy()
character.HumanoidRootPart.Position = Vector3.new(0, 40, 0)
marker:Fire(nil)
check("no dust in the air", workspace.Terrain:FindFirstChild("Dust") == nil)
connection:Disconnect()
```
