---
id: gb-world-vfx-tether-beam
category: vfx-beam-trail
topics: Beam, tether, Heartbeat, break distance, attachments
source: original
---
# Request
I'm making a "soul link" ability that tethers two players with a glowing beam. The link should break (beam removed, callback fired) if they get more than 40 studs apart or either one dies. How would you write that on the server?

# Answer
Create one Beam between an attachment on each player's root; beams track their attachments automatically, so the only per-frame work is a distance check on Heartbeat. Breaking is a single idempotent function that disconnects everything, destroys the beam and fires the callback once.

```lua
--!strict
-- ModuleScript: ServerScriptService.SoulLink
export type Link = {
	isActive: () -> boolean,
	breakLink: () -> (),
}

local RunService = game:GetService("RunService")

local SoulLink = {}

function SoulLink.new(rootA: BasePart, rootB: BasePart, maxLength: number, onBroken: (() -> ())?): Link
	local attachmentA = Instance.new("Attachment")
	attachmentA.Name = "SoulLinkAttachment"
	attachmentA.Parent = rootA
	local attachmentB = Instance.new("Attachment")
	attachmentB.Name = "SoulLinkAttachment"
	attachmentB.Parent = rootB

	local beam = Instance.new("Beam")
	beam.Attachment0 = attachmentA
	beam.Attachment1 = attachmentB
	beam.FaceCamera = true
	beam.Width0 = 0.4
	beam.Width1 = 0.4
	beam.LightEmission = 1
	beam.Parent = attachmentA

	local active = true
	local connections: { RBXScriptConnection } = {}

	local function breakLink()
		if not active then
			return
		end
		active = false
		for _, connection in connections do
			connection:Disconnect()
		end
		attachmentA:Destroy()
		attachmentB:Destroy()
		if onBroken then
			onBroken()
		end
	end

	local function watchDeath(root: BasePart): RBXScriptConnection?
		local model = root.Parent
		local humanoid = if model then model:FindFirstChildOfClass("Humanoid") else nil
		return if humanoid then humanoid.Died:Connect(breakLink) else nil
	end

	connections[#connections + 1] = RunService.Heartbeat:Connect(function()
		if rootA.Parent == nil or rootB.Parent == nil or (rootA.Position - rootB.Position).Magnitude > maxLength then
			breakLink()
		end
	end)
	for _, root in { rootA, rootB } do
		local deathConnection = watchDeath(root)
		if deathConnection then
			connections[#connections + 1] = deathConnection
		end
	end

	return {
		isActive = function(): boolean
			return active
		end,
		breakLink = breakLink,
	}
end

return SoulLink
```

- Destroying the attachments also destroys the beam parented under one of them, so there is a single cleanup path.
- `rootA.Parent == nil` covers a player leaving or a character being removed between frames.
- One distance check per Heartbeat costs almost nothing; add a RopeConstraint only if the players should also be pulled together physically.

# Test
```lua
local p1 = __makePlayer(16, "LinkA")
local c1 = __makeCharacter(p1, Vector3.new(0, 3, 0))
local p2 = __makePlayer(17, "LinkB")
local c2 = __makeCharacter(p2, Vector3.new(10, 3, 0))
local broken = 0
local link = item.new(c1.HumanoidRootPart, c2.HumanoidRootPart, 40, function()
	broken += 1
end)
local beam = c1.HumanoidRootPart.SoulLinkAttachment:FindFirstChildOfClass("Beam")
check("beam links the two attachments", beam ~= nil and beam.Attachment1 == c2.HumanoidRootPart.SoulLinkAttachment)
__frames(10)
check("link holds within range", link.isActive())
c2.HumanoidRootPart.Position = Vector3.new(60, 3, 0)
__frames(1)
check("breaks when stretched too far", not link.isActive() and broken == 1)
check("beam and attachments removed", c1.HumanoidRootPart:FindFirstChild("SoulLinkAttachment") == nil)
link.breakLink()
check("breaking twice fires the callback once", broken == 1)

c2.HumanoidRootPart.Position = Vector3.new(10, 3, 0)
local link2 = item.new(c1.HumanoidRootPart, c2.HumanoidRootPart, 40)
c1.Humanoid.Health = 0
check("death breaks the link", not link2.isActive())
```
