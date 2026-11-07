---
id: gb-eng-debug-yield-in-heartbeat
category: engineering-debugging
topics: Heartbeat, task.wait, yielding in callbacks, thread pile-up, timers
source: original
---
# Request
I wanted lava damage once per second, so I put a wait in my Heartbeat handler. Instead players die almost instantly and the server gets laggy. Why doesn't the wait slow it down?

```lua
local RS = game:GetService("RunService")
RS.Heartbeat:Connect(function()
	for _, who in ipairs(PlayersService:GetPlayers()) do
		local hum = who.Character and who.Character:FindFirstChild("Humanoid")
		if hum and who.Character:GetAttribute("InLava") then
			hum:TakeDamage(10)
		end
	end
	task.wait(1)
end)
```

# Answer
Event handlers each run in their own thread. `task.wait(1)` only pauses that one thread; Heartbeat still fires next frame and starts a new handler, so damage happens every frame (60 per second) and about 60 sleeping threads pile up at any time. Never yield to throttle a per-frame event: accumulate `dt` and act when a full interval has passed, or run a separate loop with `task.wait`.

```lua
--!strict
-- ModuleScript: ServerScriptService.LavaDamage
local Players = game:GetService("Players")

local INTERVAL = 1
local DAMAGE = 10

local LavaDamage = {}

function LavaDamage.tick()
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		if humanoid and character and character:GetAttribute("InLava") == true then
			humanoid:TakeDamage(DAMAGE)
		end
	end
end

function LavaDamage.start(heartbeat: RBXScriptSignal): RBXScriptConnection
	local elapsed = 0
	return heartbeat:Connect(function(dt: number)
		elapsed += dt
		if elapsed < INTERVAL then
			return
		end
		elapsed -= INTERVAL
		LavaDamage.tick()
	end)
end

return LavaDamage
```

- Server script: `LavaDamage.start(game:GetService("RunService").Heartbeat)`. The handler never yields, so exactly one runs per frame and it returns immediately.
- `elapsed -= INTERVAL` (instead of resetting to 0) keeps the average rate at exactly one tick per second even when frames do not divide the interval evenly.
- An equivalent design is `task.spawn(function() while true do task.wait(INTERVAL) LavaDamage.tick() end end)`; both are fine, but do not mix a per-frame event with waits inside it.

# Test
```lua
local p = __makePlayer(1, "Hot")
local character = __makeCharacter(p)
local safe = __makePlayer(2, "Cool")
__makeCharacter(safe)
character:SetAttribute("InLava", true)
local humanoid = character:FindFirstChildOfClass("Humanoid")
local connection = item.start(game:GetService("RunService").Heartbeat)
__frames(61, 1 / 60)
check("one damage tick per second", humanoid.Health == 90)
__frames(120, 1 / 60)
check("steady rate over time", humanoid.Health == 70)
check("players out of lava unharmed", safe.Character:FindFirstChildOfClass("Humanoid").Health == 100)
connection:Disconnect()
__frames(120, 1 / 60)
check("disconnect stops damage", humanoid.Health == 70)
```
