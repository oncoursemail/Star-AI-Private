---
id: gb-world-game-team-doors
category: gameplay-systems
topics: team doors, collision groups, Teams, PhysicsService, team change
source: original
---
# Request
Each team has a base with a door only that team can walk through. I tried making the door CanCollide false on the client for team members, but exploiters just do that for every door. How do I make team-only doors properly?

# Answer
Use collision groups on the server: each team gets a player group and a door group, and a team's players do not collide with their own team's door. Character parts are assigned to their team's group on spawn and again whenever the player switches teams. That makes the door work for every honest player, but each client simulates its own character, so an exploiter can still noclip through; a server check of the room behind each door catches that.

```lua
--!strict
-- ModuleScript: ServerScriptService.TeamDoors
local PhysicsService = game:GetService("PhysicsService")
local Players = game:GetService("Players")

local TeamDoors = {}

local function register(name: string)
	if not PhysicsService:IsCollisionGroupRegistered(name) then
		PhysicsService:RegisterCollisionGroup(name)
	end
end

function TeamDoors.groupFor(team: Team?): string
	return if team then "Players_" .. team.Name else "Default"
end

function TeamDoors.setup(teams: { Team }, doors: { [Team]: { BasePart } })
	for _, team in teams do
		register("Players_" .. team.Name)
		register("Door_" .. team.Name)
	end
	for _, team in teams do
		for _, other in teams do
			PhysicsService:CollisionGroupSetCollidable("Players_" .. team.Name, "Door_" .. other.Name, team ~= other)
		end
		for _, door in doors[team] or {} do
			door.CollisionGroup = "Door_" .. team.Name
		end
	end
end

function TeamDoors.applyCharacter(player: Player)
	local character = player.Character
	if character == nil then
		return
	end
	local group = TeamDoors.groupFor(player.Team)
	for _, part in character:GetDescendants() do
		if part:IsA("BasePart") then
			part.CollisionGroup = group
		end
	end
end

-- Server-side enforcement: anyone not on `team` whose root is inside the `room` box is sent to `exit`.
function TeamDoors.enforce(team: Team, room: BasePart, exit: CFrame): number
	local moved = 0
	local half = room.Size / 2
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local root = if character then character:FindFirstChild("HumanoidRootPart") else nil
		if character and root and player.Team ~= team then
			local offset = room.CFrame:PointToObjectSpace(root.Position)
			if math.abs(offset.X) <= half.X and math.abs(offset.Y) <= half.Y and math.abs(offset.Z) <= half.Z then
				character:PivotTo(exit)
				moved += 1
			end
		end
	end
	return moved
end

function TeamDoors.track(player: Player)
	player.CharacterAdded:Connect(function()
		TeamDoors.applyCharacter(player)
	end)
	player:GetPropertyChangedSignal("Team"):Connect(function()
		TeamDoors.applyCharacter(player)
	end)
	TeamDoors.applyCharacter(player)
end

function TeamDoors.trackAll()
	Players.PlayerAdded:Connect(TeamDoors.track)
	for _, player in Players:GetPlayers() do
		TeamDoors.track(player)
	end
end

return TeamDoors
```

Setup on the server: `TeamDoors.setup({ Teams.Red, Teams.Blue }, { [Teams.Red] = { workspace.RedBase.Door }, [Teams.Blue] = { workspace.BlueBase.Door } })`, then `TeamDoors.trackAll()`, then a loop that calls `TeamDoors.enforce(Teams.Red, workspace.RedBase.Inside, workspace.RedBase.Outside.CFrame)` (and the same for Blue) every half second. `Inside` is an invisible, non-colliding box covering the room.

- The groups replicate, so honest clients get the right collisions without any LocalScript. They do not stop a cheater: the player's client owns its character's physics and the server accepts the positions it reports, which is why `enforce` checks the room on the server.
- Re-applying on `Team` changes covers team switches mid-life; on respawn the new character is assigned right away.
- Accessories and tools added after spawning keep the Default group; if they matter for collisions, also handle `character.DescendantAdded`.

# Test
```lua
local PhysicsService = game:GetService("PhysicsService")
local teams = game:GetService("Teams")
local red = Instance.new("Team")
red.Name = "Red"
red.Parent = teams
local blue = Instance.new("Team")
blue.Name = "Blue"
blue.Parent = teams
local redDoor = Instance.new("Part")
redDoor.Parent = workspace
local blueDoor = Instance.new("Part")
blueDoor.Parent = workspace
item.setup({ red, blue }, { [red] = { redDoor }, [blue] = { blueDoor } })
check("own team passes its door", PhysicsService:CollisionGroupsAreCollidable("Players_Red", "Door_Red") == false)
check("other team is blocked", PhysicsService:CollisionGroupsAreCollidable("Players_Red", "Door_Blue") == true)
check("doors assigned to their groups", redDoor.CollisionGroup == "Door_Red" and blueDoor.CollisionGroup == "Door_Blue")

item.trackAll()
local player = __makePlayer(171, "Switcher")
player.Team = red
local character = __makeCharacter(player)
check("character parts join the team group", character.HumanoidRootPart.CollisionGroup == "Players_Red")
player.Team = blue
check("team switch reassigns the group", character.Head.CollisionGroup == "Players_Blue")
player.Team = nil
check("no team falls back to Default", character.Head.CollisionGroup == "Default")

local room = Instance.new("Part")
room.Anchored = true
room.Size = Vector3.new(20, 10, 20)
room.Position = Vector3.new(100, 5, 0)
room.Parent = workspace
local exit = CFrame.new(70, 3, 0)
player.Team = blue
character:PivotTo(CFrame.new(100, 3, 0))
check("intruder from another team is sent out", item.enforce(red, room, exit) == 1 and (character.HumanoidRootPart.Position - exit.Position).Magnitude < 1e-6)
player.Team = red
character:PivotTo(CFrame.new(100, 3, 0))
check("own team may stay inside", item.enforce(red, room, exit) == 0 and (character.HumanoidRootPart.Position - Vector3.new(100, 3, 0)).Magnitude < 1e-6)
```
