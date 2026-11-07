---
id: gb-world-cs-damage-zones
category: world-collectionservice
topics: CollectionService, damage zone, attributes, GetPartsInPart, damage over time
source: original
---
# Request
I want lava and poison gas areas that damage players every second while they stand inside, with the damage and interval set per area. Touched/TouchEnded is unreliable for "is the player still inside". How would you build this with tags?

# Answer
Tag each zone part "DamageZone" with `Damage` and `Interval` attributes. One server loop checks, per zone, which characters overlap it using `GetPartsInPart`, and damages each character once per that zone's interval. Overlap queries answer "who is inside right now" directly, so there is no enter/leave bookkeeping to get wrong.

```lua
--!strict
-- ModuleScript: ServerScriptService.DamageZones
local CollectionService = game:GetService("CollectionService")
local Players = game:GetService("Players")

local DamageZones = {}

local function charactersIn(zone: BasePart): { Model }
	local found: { Model } = {}
	local seen: { [Model]: boolean } = {}
	for _, part in workspace:GetPartsInPart(zone) do
		local model = part:FindFirstAncestorOfClass("Model")
		if model and not seen[model] and Players:GetPlayerFromCharacter(model) then
			seen[model] = true
			table.insert(found, model)
		end
	end
	return found
end

function DamageZones.start(tick: number): () -> ()
	local lastHit: { [BasePart]: { [Model]: number } } = {}
	local running = true

	task.spawn(function()
		while running do
			local now = os.clock()
			for _, zone in CollectionService:GetTagged("DamageZone") do
				if zone:IsA("BasePart") then
					local damage, interval = zone:GetAttribute("Damage"), zone:GetAttribute("Interval")
					if type(damage) == "number" and type(interval) == "number" and damage > 0 then
						local hits = lastHit[zone] or {}
						lastHit[zone] = hits
						for _, character in charactersIn(zone) do
							local humanoid = character:FindFirstChildOfClass("Humanoid")
							if humanoid and humanoid.Health > 0 and now - (hits[character] or -math.huge) >= interval then
								hits[character] = now
								humanoid:TakeDamage(damage)
							end
						end
						-- Forget respawned or departed characters so the table does not keep old models alive.
						for character in hits do
							if character.Parent == nil then
								hits[character] = nil
							end
						end
					end
				end
			end
			task.wait(tick)
		end
	end)

	local removed = CollectionService:GetInstanceRemovedSignal("DamageZone"):Connect(function(zone: Instance)
		if zone:IsA("BasePart") then
			lastHit[zone] = nil
		end
	end)

	return function()
		running = false
		removed:Disconnect()
	end
end

return DamageZones
```

Start once on the server: `DamageZones.start(0.2)`.

- Zone parts should have `CanCollide` off (players walk into the gas) but `CanQuery` on, since overlap queries skip non-queryable parts.
- Each zone keeps its own per-character timer, so standing where lava and gas overlap applies both, each at its own rate.
- Attributes are read every pass, so changing `Damage` in a live server (or from a difficulty setting) takes effect immediately.
- `TakeDamage` respects spawn ForceFields, so protected players standing in a zone are not hurt.

# Test
```lua
local cs = game:GetService("CollectionService")
local lava = Instance.new("Part")
lava.Anchored = true
lava.CanCollide = false
lava.Size = Vector3.new(10, 4, 10)
lava.Position = Vector3.new(0, 2, 0)
lava:SetAttribute("Damage", 10)
lava:SetAttribute("Interval", 1)
lava.Parent = workspace
cs:AddTag(lava, "DamageZone")

local inside = __makePlayer(121, "Hot")
local hot = __makeCharacter(inside, Vector3.new(0, 3, 0))
local outside = __makePlayer(122, "Cool")
local cool = __makeCharacter(outside, Vector3.new(40, 3, 0))
local npc = __buildRig(Vector3.new(2, 3, 0))
npc.Parent = workspace

local stop = item.start(0.2)
check("damage applied on entry", hot.Humanoid.Health == 90)
__advance(0.5)
check("interval respected", hot.Humanoid.Health == 90)
__advance(0.6)
check("damaged again after the interval", hot.Humanoid.Health == 80)
check("players outside and NPCs are untouched", cool.Humanoid.Health == 100 and npc.Humanoid.Health == 100)
lava:SetAttribute("Damage", 30)
__advance(1.15)
check("attribute changes apply live", hot.Humanoid.Health == 50)
cs:RemoveTag(lava, "DamageZone")
__advance(3)
check("untagged zone stops hurting", hot.Humanoid.Health == 50)
stop()
```
