---
id: gb-src-attribute-crop-growth
category: gameplay-systems
topics: attributes, SetAttribute, GetAttributeChangedSignal, AttributeChanged, farming, growth
source: adapted
source_id: creator-docs
source_path: content/en-us/scripting/attributes.md
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
For my farming game each cabbage should grow over time on the server, have a configurable growth rate, and become harvestable when grown. Clients should update visuals when it changes. Should I use IntValues or attributes?

# Answer
Use attributes on the crop part: they replicate like values without extra instances, designers can tune `GrowthRate` in the Properties panel, and `GetAttributeChangedSignal` lets any script react. The server owns `Growth` (harvestable at 100); clients only listen.

```lua
--!strict
local RunService = game:GetService("RunService")

local MAX_GROWTH = 100
local TICK_SECONDS = 1

local Crop = {}

function Crop.setup(crop: BasePart)
	if crop:GetAttribute("GrowthRate") == nil then
		crop:SetAttribute("GrowthRate", 2)
	end
	crop:SetAttribute("Growth", 0)
end

function Crop.isHarvestable(crop: BasePart): boolean
	local growth = crop:GetAttribute("Growth")
	return typeof(growth) == "number" and growth >= MAX_GROWTH
end

function Crop.step(crop: BasePart, dt: number)
	local rate = crop:GetAttribute("GrowthRate")
	local growth = crop:GetAttribute("Growth")
	if typeof(rate) ~= "number" or typeof(growth) ~= "number" or growth >= MAX_GROWTH then
		return
	end
	crop:SetAttribute("Growth", math.min(MAX_GROWTH, growth + rate * dt))
end

function Crop.harvest(crop: BasePart): boolean
	if not Crop.isHarvestable(crop) then
		return false
	end
	crop:SetAttribute("Growth", 0)
	return true
end

function Crop.startServerLoop(crops: { BasePart }): RBXScriptConnection
	for _, crop in crops do
		Crop.setup(crop)
	end
	local pending = 0
	return RunService.Heartbeat:Connect(function(dt: number)
		pending += dt
		if pending < TICK_SECONDS then
			return
		end
		local elapsed = pending
		pending = 0
		for _, crop in crops do
			Crop.step(crop, elapsed)
		end
	end)
end

return Crop
```

Client side, the visuals follow the attribute:

```lua
--!strict
local function bindVisuals(crop: BasePart)
	local function refresh()
		local growth = crop:GetAttribute("Growth")
		local scale = if typeof(growth) == "number" then 0.3 + 0.7 * growth / 100 else 0.3
		crop.Size = Vector3.one * 2 * scale
	end
	crop:GetAttributeChangedSignal("Growth"):Connect(refresh)
	refresh()
end

return bindVisuals
```

- Attribute names are plain strings and values are limited to simple types (number, string, boolean, Vector3, Color3, ...); tables are not allowed.
- `harvest` must run on the server after validating the request (distance, ownership), so a client cannot reset or farm crops itself.
- Growth is written once per second, not every frame: each attribute change is sent to every client, so per-frame writes on many crops would flood the network.
- Setting `GrowthRate` per crop in Studio changes speed with no code change.

# Test
```lua
local cabbage = Instance.new("Part")
cabbage.Parent = workspace
local conn = item.startServerLoop({ cabbage })
check("defaults applied", cabbage:GetAttribute("GrowthRate") == 2 and cabbage:GetAttribute("Growth") == 0)
check("cannot harvest early", item.harvest(cabbage) == false)
__frames(30, 1 / 60)
check("no write before a full tick", cabbage:GetAttribute("Growth") == 0)
__frames(10, 1)
check("grows with time", math.abs(cabbage:GetAttribute("Growth") - 21) < 1e-6)
__frames(60, 1)
check("caps at 100 and becomes harvestable", cabbage:GetAttribute("Growth") == 100 and item.isHarvestable(cabbage))
check("harvest resets", item.harvest(cabbage) == true and cabbage:GetAttribute("Growth") == 0)
conn:Disconnect()
```
