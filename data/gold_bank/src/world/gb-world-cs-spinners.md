---
id: gb-world-cs-spinners
category: world-collectionservice
topics: CollectionService, spinning parts, attributes, Heartbeat, client animation
source: original
---
# Request
I have lots of decorative spinning parts (coins, fans, windmills) each with a while loop script that rotates it a bit every `wait()`. It looks choppy and there are hundreds of scripts. Can I do it with tags and one script, with each part choosing its own speed?

# Answer
Tag the parts "Spinner" and give them a `SpinSpeed` attribute in degrees per second. One LocalScript keeps a set of tagged parts and rotates all of them each frame by `speed * dt`, which is smooth at any frame rate. Spinning cosmetics on the client also means the server replicates nothing.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Spinners
local CollectionService = game:GetService("CollectionService")
local RunService = game:GetService("RunService")

local TAG = "Spinner"

local Spinners = {}

function Spinners.start(): () -> ()
	local active: { [BasePart]: boolean } = {}

	local function onAdded(instance: Instance)
		if instance:IsA("BasePart") then
			active[instance] = true
		end
	end

	local addedConnection = CollectionService:GetInstanceAddedSignal(TAG):Connect(onAdded)
	local removedConnection = CollectionService:GetInstanceRemovedSignal(TAG):Connect(function(instance: Instance)
		if instance:IsA("BasePart") then
			active[instance] = nil
		end
	end)
	for _, instance in CollectionService:GetTagged(TAG) do
		onAdded(instance)
	end

	local stepConnection = RunService.Heartbeat:Connect(function(dt: number)
		for part in active do
			local speed = part:GetAttribute("SpinSpeed")
			if type(speed) == "number" and speed ~= 0 then
				part.CFrame *= CFrame.Angles(0, math.rad(speed * dt), 0)
			end
		end
	end)

	return function()
		addedConnection:Disconnect()
		removedConnection:Disconnect()
		stepConnection:Disconnect()
		table.clear(active)
	end
end

return Spinners
```

Start it once from a LocalScript in StarterPlayerScripts: `require(ReplicatedStorage.Spinners).start()`.

- Rotating by `speed * dt` makes the spin rate independent of frame rate; a fixed step per `wait()` slows down on weak devices and stutters.
- Spinner parts should be Anchored; for spinners that must push players (a sweeper bar), use a HingeConstraint motor on the server instead so physics is authoritative.
- With StreamingEnabled, parts that stream out fire the removed signal and drop out of the set, so far-away spinners cost nothing.
- Speeds come from attributes, so designers tune each part in Studio, and negative values spin the other way.

# Test
```lua
local cs = game:GetService("CollectionService")
local fan = Instance.new("Part")
fan.Anchored = true
fan:SetAttribute("SpinSpeed", 90)
fan.Parent = workspace
cs:AddTag(fan, "Spinner")
local stop = item.start()
__frames(60, 1 / 60)
check("spins at the attribute speed", (fan.CFrame.LookVector - Vector3.new(-1, 0, 0)).Magnitude < 1e-6)

local coin = Instance.new("Part")
coin:SetAttribute("SpinSpeed", -180)
coin.Parent = workspace
cs:AddTag(coin, "Spinner")
__frames(30, 1 / 60)
check("parts tagged later spin too, negative is reversed", (coin.CFrame.LookVector - Vector3.new(1, 0, 0)).Magnitude < 1e-6)

cs:RemoveTag(fan, "Spinner")
local before = fan.CFrame
__frames(10, 1 / 60)
check("untagged parts stop", fan.CFrame == before)
local still = Instance.new("Part")
still.Parent = workspace
cs:AddTag(still, "Spinner")
__frames(10, 1 / 60)
check("missing attribute means no spin", still.CFrame == CFrame.identity)
stop()
local frozen = coin.CFrame
__frames(10, 1 / 60)
check("stop halts everything", coin.CFrame == frozen)
```
