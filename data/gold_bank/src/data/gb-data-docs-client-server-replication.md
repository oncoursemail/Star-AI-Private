---
id: gb-data-docs-client-server-replication
category: docs-question
topics: replication, FilteringEnabled, network ownership, client authority, server trust
source: original
---
# Request
I'm confused about what replicates. If a LocalScript changes a part's color or a leaderstat, does the server see it? What things DO go from the client to the server automatically?

# Answer
Changes the server makes to replicated instances reach clients; changes a client makes to instances stay on that client. A LocalScript recolouring a part or editing a leaderstat only changes its own view. The automatic exceptions are physics the client has network ownership of (its own character's movement, plus unanchored parts the engine assigns to it automatically because they are near it, or that the server gave it), deleting parts of its own character, animations played on its own character through the Animator, and the events and requests you send yourself (remotes, prompt and click interactions, chat). Everything else must go through a remote that the server validates.

```lua
--!strict
-- Server: trust what the server can see, re-check what the client controls.
local Players = game:GetService("Players")

local MAX_SPEED = 32 -- generous above WalkSpeed 16 to allow for jumps and knockback

-- Character position replicates from the owning client, so it is useful but not trustworthy:
-- sanity-check it on the server rather than believing it blindly.
local function checkMovement(player: Player, lastPosition: Vector3, dt: number): (boolean, Vector3?)
	local character = player.Character
	local root: BasePart? = if character then character:FindFirstChild("HumanoidRootPart") else nil
	if root == nil then
		return true, nil
	end
	local position = root.Position
	local horizontal = Vector3.new(position.X - lastPosition.X, 0, position.Z - lastPosition.Z)
	return horizontal.Magnitude <= MAX_SPEED * dt + 1, position
end

local function onPlayer(player: Player)
	-- leaderstats created here exist for everyone; a LocalScript changing them changes nothing on the server
	local stats = Instance.new("Folder")
	stats.Name = "leaderstats"
	stats.Parent = player
end

Players.PlayerAdded:Connect(onPlayer)
for _, player in Players:GetPlayers() do
	onPlayer(player)
end

return checkMovement
```

- Client-owned physics is why speed and teleport exploits exist, and why an unanchored part near a player can be moved by that player's client unless you anchor it or call `part:SetNetworkOwner(nil)`; checks like `checkMovement` (with tolerance and a strike system) are the server's answer.
- ServerStorage and ServerScriptService never replicate, so secrets and server modules belong there; anything in ReplicatedStorage or Workspace can be read by clients.
- GUIs a client builds in its PlayerGui are invisible to the server, which is fine; the server only cares about the requests those GUIs send.

# Test
```lua
local p = __makePlayer(1, "Runner")
local character = __makeCharacter(p, Vector3.new(0, 3, 0))
check("server-created leaderstats exist", p:FindFirstChild("leaderstats") ~= nil)
character.HumanoidRootPart.Position = Vector3.new(10, 3, 0)
local ok, now = item(p, Vector3.new(0, 3, 0), 1)
check("normal movement passes", ok and now == Vector3.new(10, 3, 0))
character.HumanoidRootPart.Position = Vector3.new(500, 3, 0)
check("teleport-like movement is flagged", not item(p, Vector3.new(10, 3, 0), 1))
character.HumanoidRootPart.Position = Vector3.new(10, 80, 0)
check("vertical movement is not counted as horizontal speed", item(p, Vector3.new(10, 3, 0), 0.5))
```
