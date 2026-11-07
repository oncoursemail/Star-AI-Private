---
id: gb-eng-stream-replication-focus-cutscene
category: performance-streaming
topics: ReplicationFocus, cutscene, StreamingEnabled, camera, server
source: original
---
# Request
I have a boss intro cutscene where the camera flies over the boss arena, far from where players stand. With streaming on, the arena is empty or low-detail during the cutscene. How do I get the arena streamed in for the duration of the cutscene and then go back to normal?

# Answer
Set `player.ReplicationFocus` on the server to a part at the area the camera is looking at; streaming then centres on that part instead of the character. Restore it to nil afterwards so streaming follows the character again. A small module keeps the restore in one place, even if the cutscene is interrupted.

```lua
--!strict
-- ModuleScript: ServerScriptService.FocusControl
local FocusControl = {}

local focusParts: { [Player]: BasePart } = {}

function FocusControl.focusAt(player: Player, position: Vector3, anchorFolder: Instance): BasePart
	local part = focusParts[player]
	if part == nil then
		local newPart = Instance.new("Part")
		newPart.Name = `Focus_{player.UserId}`
		newPart.Anchored = true
		newPart.CanCollide = false
		newPart.CanQuery = false
		newPart.CanTouch = false
		newPart.Transparency = 1
		newPart.Parent = anchorFolder
		focusParts[player] = newPart
		part = newPart
	end
	part.Position = position
	player.ReplicationFocus = part
	return part
end

function FocusControl.clear(player: Player): ()
	player.ReplicationFocus = nil
	local part = focusParts[player]
	if part then
		part:Destroy()
		focusParts[player] = nil
	end
end

function FocusControl.during(player: Player, position: Vector3, anchorFolder: Instance, run: () -> ()): boolean
	FocusControl.focusAt(player, position, anchorFolder)
	local ok, err = pcall(run)
	FocusControl.clear(player)
	if not ok then
		warn(`cutscene failed for {player.Name}: {err}`)
	end
	return ok
end

return FocusControl
```

- Usage: `FocusControl.during(player, arena.Position, workspace.FocusParts, function() cutsceneRemote:FireClient(player, "BossIntro") task.wait(8) end)`; the client plays the camera, the server owns the focus.
- Hook `Players.PlayerRemoving` to `FocusControl.clear` so focus parts of players who leave mid-cutscene are destroyed.
- Combine with `player:RequestStreamAroundAsync(arena.Position)` before starting if the camera's first shot must be fully loaded.

# Test
```lua
local folder = Instance.new("Folder")
folder.Parent = workspace
local p = __makePlayer(1, "Viewer")
local part = item.focusAt(p, Vector3.new(800, 20, 0), folder)
check("focus set to a part at the arena", p.ReplicationFocus == part and part.Position == Vector3.new(800, 20, 0))
local again = item.focusAt(p, Vector3.new(810, 20, 0), folder)
check("focus part reused", again == part and #folder:GetChildren() == 1)
item.clear(p)
check("clear restores and cleans up", p.ReplicationFocus == nil and #folder:GetChildren() == 0)
local seen
local ok
task.spawn(function()
	ok = item.during(p, Vector3.new(1, 2, 3), folder, function()
		seen = p.ReplicationFocus
		task.wait(1)
	end)
end)
check("focus active during cutscene", seen ~= nil and seen.Position == Vector3.new(1, 2, 3))
__advance(1.1)
check("restored after cutscene", ok == true and p.ReplicationFocus == nil)
check("restored even when cutscene errors", item.during(p, Vector3.zero, folder, function() error("boom", 0) end) == false and p.ReplicationFocus == nil)
```
