---
id: gb-eng-debug-touched-accessory-error
category: engineering-debugging
topics: Touched, Humanoid nil, accessories, debounce, damage brick
source: original
---
# Request
My spike trap throws "Humanoid is not a valid member of Accessory" sometimes, and when it does work it kills players instantly instead of doing 20 damage. Script inside the spike part:

```lua
script.Parent.Touched:Connect(function(otherPart)
	otherPart.Parent.Humanoid:TakeDamage(20)
end)
```

# Answer
Two bugs. `otherPart` can be any part: a hat's Handle (whose parent is an Accessory, not the character), a dropped tool, or a loose brick, so `otherPart.Parent.Humanoid` errors. And `Touched` fires for every touching body part, many times per second, so one step deals 20 damage dozens of times. Resolve the character safely with `FindFirstAncestorOfClass("Model")` and `FindFirstChildOfClass("Humanoid")`, and give each character a cooldown.

```lua
--!strict
-- Script inside the spike part
local spike = script.Parent :: BasePart

local DAMAGE = 20
local COOLDOWN = 1

local lastHit: { [Model]: number } = {}

local function characterFrom(hit: BasePart): (Model?, Humanoid?)
	local model = hit:FindFirstAncestorOfClass("Model")
	while model do
		local humanoid = model:FindFirstChildOfClass("Humanoid")
		if humanoid then
			return model, humanoid
		end
		model = model:FindFirstAncestorOfClass("Model")
	end
	return nil, nil
end

spike.Touched:Connect(function(hit: BasePart)
	local character, humanoid = characterFrom(hit)
	if character == nil or humanoid == nil or humanoid.Health <= 0 then
		return
	end
	local now = os.clock()
	local last = lastHit[character]
	if last and now - last < COOLDOWN then
		return -- per-character cooldown: one hit per second however many parts touch
	end
	if last == nil then
		character.Destroying:Once(function()
			lastHit[character] = nil
		end)
	end
	lastHit[character] = now
	humanoid:TakeDamage(DAMAGE)
end)
```

- Walking up through ancestor Models handles parts nested inside accessories or tools held by the character.
- The cooldown table is keyed by character and cleared on `Destroying`, so it does not grow with every respawn.
- `TakeDamage` respects ForceFields (fresh spawns are safe); setting `Health` directly would not.

# Test
```lua
local spikePart = Instance.new("Part")
spikePart.Parent = workspace
script.Parent = spikePart
```
```lua
local p = __makePlayer(1, "Walker")
local character = __makeCharacter(p)
local humanoid = character:FindFirstChildOfClass("Humanoid")
local hat = Instance.new("Accessory")
local handle = Instance.new("Part")
handle.Name = "Handle"
handle.Parent = hat
hat.Parent = character
local spike = script.Parent
spike.Touched:Fire(character.HumanoidRootPart)
spike.Touched:Fire(character.Head)
spike.Touched:Fire(handle)
check("one hit despite many touching parts", humanoid.Health == 80)
__advance(1.1)
spike.Touched:Fire(handle)
check("accessory handle resolves to character after cooldown", humanoid.Health == 60)
local brick = Instance.new("Part")
brick.Parent = workspace
check("non-character part ignored without error", pcall(function() spike.Touched:Fire(brick) end))
local loose = Instance.new("Part")
local looseHat = Instance.new("Accessory")
loose.Parent = looseHat
looseHat.Parent = workspace
spike.Touched:Fire(loose)
check("dropped accessory ignored", humanoid.Health == 60)
```
