---
id: gb-world-phys-anti-fling
category: physics
topics: anti-fling, AssemblyLinearVelocity, AssemblyAngularVelocity, safe position, server check
source: original
---
# Request
Players keep getting flung across the map, either from glitchy physics on spinning parts or from exploiters. I'd like a server-side check that catches crazy velocities, stops the character and puts it back where it last stood safely.

# Answer
Sample every character a few times per second on the server: if linear or angular velocity is far beyond anything legitimate, zero both and pivot the character back to its last safe position; otherwise record the current position as safe. A strike counter per player tells you who triggers it constantly.

```lua
--!strict
-- ModuleScript: ServerScriptService.AntiFling
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")

export type Options = { maxLinear: number, maxAngular: number, interval: number }

local AntiFling = {}

function AntiFling.isFlung(linear: Vector3, angular: Vector3, options: Options): boolean
	return linear.Magnitude > options.maxLinear or angular.Magnitude > options.maxAngular
end

function AntiFling.start(options: Options, onStrike: ((player: Player, strikes: number) -> ())?): () -> ()
	local safe: { [Player]: CFrame } = {}
	local strikes: { [Player]: number } = {}
	local elapsed = 0

	local heartbeat = RunService.Heartbeat:Connect(function(dt: number)
		elapsed += dt
		if elapsed < options.interval then
			return
		end
		elapsed = 0
		for _, player in Players:GetPlayers() do
			local character = player.Character
			local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
			if character and root and root:IsA("BasePart") then
				if AntiFling.isFlung(root.AssemblyLinearVelocity, root.AssemblyAngularVelocity, options) then
					root.AssemblyLinearVelocity = Vector3.zero
					root.AssemblyAngularVelocity = Vector3.zero
					local lastSafe = safe[player]
					if lastSafe then
						character:PivotTo(lastSafe)
					end
					local count = (strikes[player] or 0) + 1
					strikes[player] = count
					local callback = onStrike
					if callback then
						callback(player, count)
					end
				else
					safe[player] = character:GetPivot()
				end
			end
		end
	end)

	local removing = Players.PlayerRemoving:Connect(function(player: Player)
		safe[player] = nil
		strikes[player] = nil
	end)

	return function()
		heartbeat:Disconnect()
		removing:Disconnect()
	end
end

return AntiFling
```

Starting it: `AntiFling.start({ maxLinear = 250, maxAngular = 40, interval = 0.2 })`, with an `onStrike` that logs or kicks after repeated strikes.

- Thresholds must sit well above your fastest legitimate movement (dashes, launch pads, vehicles); measure those first and add margin.
- The player's client simulates its own character, so the owner can overwrite the server's velocity write; the server `PivotTo` is what reliably reaches it. A determined exploiter can keep fighting the reset, which is why strikes are counted.
- Recording the safe position only on clean samples means the reset never puts someone back mid-fling.
- Pair this with a "Players" collision group that does not collide with itself; most player-on-player flings disappear entirely.

# Test
```lua
local options = { maxLinear = 250, maxAngular = 40, interval = 0.2 }
check("normal running is fine", not item.isFlung(Vector3.new(16, 0, 0), Vector3.zero, options))
check("spinning is caught", item.isFlung(Vector3.zero, Vector3.new(0, 90, 0), options))

local player = __makePlayer(35, "Flingee")
local character = __makeCharacter(player, Vector3.new(0, 3, 0))
local struck = {}
local stop = item.start(options, function(p, n)
	struck[p] = n
end)
__frames(15)
local root = character.HumanoidRootPart
character:PivotTo(CFrame.new(500, 300, 0))
root.AssemblyLinearVelocity = Vector3.new(900, 400, 0)
__frames(15)
check("flung character is stopped", root.AssemblyLinearVelocity == Vector3.zero)
check("and returned to the last safe spot", (root.Position - Vector3.new(0, 3, 0)).Magnitude < 1e-6)
check("strike recorded", struck[player] == 1)
__frames(15)
check("no strike while standing still", struck[player] == 1)
stop()
root.AssemblyLinearVelocity = Vector3.new(900, 0, 0)
__frames(15)
check("stopped checker leaves characters alone", struck[player] == 1)
```
