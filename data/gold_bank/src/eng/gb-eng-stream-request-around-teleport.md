---
id: gb-eng-stream-request-around-teleport
category: performance-streaming
topics: RequestStreamAroundAsync, StreamingEnabled, teleport within place, falling through map, pcall
source: original
---
# Request
With StreamingEnabled, when my server moves a player's character to a faraway arena (same place, not TeleportService), they sometimes fall through the floor or stand in an empty void for a second. How do I make sure the destination is loaded on their client first?

# Answer
Call `player:RequestStreamAroundAsync(position, timeout)` on the server before moving the character: it yields until the client has streamed in the area around that point (or the timeout passes). It can fail, so wrap it in `pcall`, and move the character even on failure so nobody gets stuck. Briefly anchoring the root covers the remaining gap.

```lua
--!strict
-- ModuleScript: ServerScriptService.ArenaTeleport
local STREAM_TIMEOUT = 5
local SETTLE_TIME = 0.5

local ArenaTeleport = {}

function ArenaTeleport.moveTo(player: Player, destination: CFrame): boolean
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if character == nil or root == nil or not root:IsA("BasePart") then
		return false
	end
	local ok, err = pcall(function()
		player:RequestStreamAroundAsync(destination.Position, STREAM_TIMEOUT)
	end)
	if not ok then
		warn(`stream request failed for {player.Name}: {err}`)
	end
	-- the request yields; the player may have left or respawned meanwhile
	if player.Parent == nil or player.Character ~= character then
		return false
	end
	root.Anchored = true
	character:PivotTo(destination)
	task.delay(SETTLE_TIME, function()
		if root.Parent then
			root.Anchored = false
		end
	end)
	return ok
end

return ArenaTeleport
```

- `RequestStreamAroundAsync` is a server-side request about that player's client; call it for each player you move, in parallel (`task.spawn` per player) when moving a whole team.
- Re-check the player and character after the yield: moving a character that respawned during the wait would teleport the wrong body.
- If players often go to the same spot (a lobby), placing a `Persistent` model there removes the wait entirely.

# Test
```lua
local p = __makePlayer(1, "Fighter")
__makeCharacter(p, Vector3.new(0, 3, 0))
local requests = {}
p.RequestStreamAroundAsync = function(_, position, timeout)
	table.insert(requests, { position = position, timeout = timeout })
	task.wait(0.3)
end
local result
task.spawn(function()
	result = item.moveTo(p, CFrame.new(5000, 10, 5000))
end)
check("waits for streaming before moving", requests[1] and requests[1].position == Vector3.new(5000, 10, 5000) and p.Character.HumanoidRootPart.Position.X == 0)
__advance(0.35)
local root = p.Character.HumanoidRootPart
check("character moved after stream request", result == true and root.Position.X == 5000 and root.Anchored == true)
__advance(1)
check("root unanchored after settling", root.Anchored == false)
p.RequestStreamAroundAsync = function()
	error("request rejected")
end
check("failure still moves the player", item.moveTo(p, CFrame.new(-100, 10, 0)) == false and root.Position.X == -100)
local q = __makePlayer(2, "Respawner")
__makeCharacter(q)
q.RequestStreamAroundAsync = function()
	task.wait(0.3)
end
local moved
task.spawn(function()
	moved = item.moveTo(q, CFrame.new(900, 10, 0))
end)
__makeCharacter(q, Vector3.new(1, 3, 1))
__advance(0.5)
check("respawn during wait cancels move", moved == false and q.Character.HumanoidRootPart.Position.X == 1)
```
