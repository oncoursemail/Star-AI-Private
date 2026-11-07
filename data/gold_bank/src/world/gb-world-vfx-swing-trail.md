---
id: gb-world-vfx-swing-trail
category: vfx-beam-trail
topics: Trail, sword swing, animation markers, attachments, Enabled
source: original
---
# Request
My sword has a Trail that is always on, so it leaves streaks even when I'm just walking around. I only want the trail during the actual slash. I have "TrailOn" and "TrailOff" markers in the swing animation.

# Answer
Give the blade two attachments (base and tip), keep the Trail disabled by default and toggle `Enabled` from the markers. Do the toggling where it replicates: a property set by a LocalScript stays on that one client, so other players would still see the old trail. Also switch it off when the track stops, so a cancelled swing (stun, unequip) never leaves the trail stuck on.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SwingTrail
local SwingTrail = {}

function SwingTrail.setup(blade: BasePart, template: Trail?): Trail
	local base = blade:FindFirstChild("TrailBase")
	local tip = blade:FindFirstChild("TrailTip")
	assert(base and tip and base:IsA("Attachment") and tip:IsA("Attachment"), "blade needs TrailBase and TrailTip attachments")

	local existing = blade:FindFirstChildOfClass("Trail")
	local trail = existing or if template then template:Clone() else Instance.new("Trail")
	if existing == nil then
		trail.Lifetime = 0.15
		trail.Parent = blade
	end
	trail.Attachment0 = base
	trail.Attachment1 = tip
	trail.Enabled = false
	return trail
end

function SwingTrail.bindToTrack(trail: Trail, track: AnimationTrack): () -> ()
	local function turnOff()
		trail.Enabled = false
	end
	local connections = {
		track:GetMarkerReachedSignal("TrailOn"):Connect(function()
			trail.Enabled = true
		end),
		track:GetMarkerReachedSignal("TrailOff"):Connect(turnOff),
		track.Stopped:Connect(turnOff),
	}
	return function()
		turnOff()
		for _, connection in connections do
			connection:Disconnect()
		end
	end
end

return SwingTrail
```

Usage in a server Script inside the tool (`Tool.Activated` also fires on the server, and an animation the server plays on a character replicates to every client):

```lua
--!strict
-- Script (server) inside the Tool, next to Blade and a SlashAnimation Animation
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local SwingTrail = require(ReplicatedStorage:WaitForChild("SwingTrail"))

local tool = script.Parent :: Tool
local slash = tool:WaitForChild("SlashAnimation") :: Animation
local trail = SwingTrail.setup(tool:WaitForChild("Blade") :: BasePart)
local track: AnimationTrack? = nil
local unbind: (() -> ())? = nil

tool.Equipped:Connect(function()
	local humanoid = tool.Parent and tool.Parent:FindFirstChildOfClass("Humanoid")
	local animator = humanoid and humanoid:FindFirstChildOfClass("Animator")
	if animator then
		local newTrack = animator:LoadAnimation(slash)
		track = newTrack
		unbind = SwingTrail.bindToTrack(trail, newTrack)
	end
end)

tool.Unequipped:Connect(function()
	if unbind then
		unbind()
		unbind = nil
	end
	if track then
		track:Stop()
		track:Destroy()
		track = nil
	end
end)

tool.Activated:Connect(function()
	if track and not track.IsPlaying then
		track:Play()
	end
end)
```

- The trail's width comes from the distance between the two attachments, so place TrailBase near the guard and TrailTip at the point.
- A short `Lifetime` (0.1-0.2 s) reads as a crisp slash; long lifetimes smear when the player turns.
- Setting `Enabled = false` lets the existing segments fade out on their own instead of disappearing.
- Playing the swing from the server starts it one round trip late for the attacker. If you keep the swing in the client for responsiveness, every client must run the binding for every character (for example from `Animator.AnimationPlayed`), because a LocalScript's `Enabled` change is not seen by anyone else.

# Test
```lua
local blade = Instance.new("Part")
local base = Instance.new("Attachment")
base.Name = "TrailBase"
base.Parent = blade
local tip = Instance.new("Attachment")
tip.Name = "TrailTip"
tip.Parent = blade
local trail = item.setup(blade)
check("trail created between the attachments and off", trail.Attachment0 == base and trail.Attachment1 == tip and trail.Enabled == false)
check("setup reuses an existing trail", item.setup(blade) == trail)

local rig = __buildRig()
local track = rig.Humanoid.Animator:LoadAnimation(Instance.new("Animation"))
local unbind = item.bindToTrack(trail, track)
track:Play()
track:GetMarkerReachedSignal("TrailOn"):Fire()
check("on during the slash", trail.Enabled)
track:GetMarkerReachedSignal("TrailOff"):Fire()
check("off after TrailOff", not trail.Enabled)
track:GetMarkerReachedSignal("TrailOn"):Fire()
track:Stop()
check("a cancelled swing turns it off", not trail.Enabled)
unbind()
track:GetMarkerReachedSignal("TrailOn"):Fire()
check("unbound track no longer toggles it", not trail.Enabled)
check("missing attachments error", not pcall(item.setup, Instance.new("Part")))
```
