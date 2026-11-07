---
id: gb-data-remote-team-change-request
category: remote-security
topics: Teams, RemoteEvent, team balance, cooldown, validation
source: original
---
# Request
I have a team select menu that fires `ChangeTeam:FireServer(teamName)`. How should the server handle it so players can't join locked teams, stack one team, or spam switches?

# Answer
Look the team up by name under the Teams service (so only real teams match), refuse teams you marked as not joinable, enforce balance (the new team may not end up with more than one extra player compared with the smallest team), and apply a per-player cooldown.

```lua
--!strict
-- Script: ServerScriptService.TeamSelect
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Teams = game:GetService("Teams")

local SWITCH_COOLDOWN = 10

local changeTeam = Instance.new("RemoteEvent")
changeTeam.Name = "ChangeTeam"
changeTeam.Parent = ReplicatedStorage

local lastSwitch: { [Player]: number } = {}

local function joinableTeam(name: unknown): Team?
	if type(name) ~= "string" or #name > 50 then
		return nil
	end
	local team = Teams:FindFirstChild(name)
	if team == nil or not team:IsA("Team") or team:GetAttribute("Joinable") ~= true then
		return nil
	end
	return team :: any
end

local function wouldUnbalance(target: Team, player: Player): boolean
	local smallest = math.huge
	for _, team in Teams:GetTeams() do
		if team ~= target and team:GetAttribute("Joinable") == true then
			local members: { Player } = team:GetPlayers()
			local count = #members
			if team == player.Team then
				count -= 1 -- the player is leaving this team
			end
			smallest = math.min(smallest, count)
		end
	end
	local joining: { Player } = target:GetPlayers()
	return smallest ~= math.huge and #joining + 1 > smallest + 1
end

local function onChangeTeam(player: Player, nameArg: unknown)
	local team = joinableTeam(nameArg)
	if team == nil or team == player.Team then
		return
	end
	local now = os.clock()
	local last = lastSwitch[player]
	if last and now - last < SWITCH_COOLDOWN then
		return
	end
	if wouldUnbalance(team, player) then
		return
	end
	lastSwitch[player] = now
	player.Team = team
end

changeTeam.OnServerEvent:Connect(onChangeTeam)
Players.PlayerRemoving:Connect(function(player: Player)
	lastSwitch[player] = nil
end)
```

- Mark joinable teams with a `Joinable` attribute in Studio; staff or VIP teams simply leave it off and can only be assigned by server code.
- Respawn the player through your normal spawn code after a switch, so nobody walks into the enemy base with the old team's character and tools.
- Send the result back with a RemoteEvent (or let the menu read `player.Team`) so the UI can explain why a switch was refused.

# Test
```lua
local Teams = game:GetService("Teams")
local function makeTeam(name, joinable)
	local team = Instance.new("Team")
	team.Name = name
	team:SetAttribute("Joinable", joinable)
	team.Parent = Teams
	return team
end
local red = makeTeam("Red", true)
local blue = makeTeam("Blue", true)
makeTeam("Staff", false)
local remote = game:GetService("ReplicatedStorage"):WaitForChild("ChangeTeam")

local p1 = __makePlayer(1, "One")
local p2 = __makePlayer(2, "Two")
local p3 = __makePlayer(3, "Three")
remote.OnServerEvent:Fire(p1, "Red")
check("can join an empty joinable team", p1.Team == red)
remote.OnServerEvent:Fire(p2, "Red")
check("cannot stack a team two ahead", p2.Team == nil)
remote.OnServerEvent:Fire(p2, "Blue")
remote.OnServerEvent:Fire(p3, "Red")
check("balanced joins are allowed", p2.Team == blue and p3.Team == red)

remote.OnServerEvent:Fire(p1, "Staff")
remote.OnServerEvent:Fire(p1, "Spectators")
remote.OnServerEvent:Fire(p1, 42)
check("locked, missing and non-string teams are refused", p1.Team == red)

__advance(11)
remote.OnServerEvent:Fire(p1, "Blue")
check("switching to an even team is allowed after the cooldown", p1.Team == blue)
remote.OnServerEvent:Fire(p1, "Red")
check("switching again inside the cooldown is refused", p1.Team == blue)
```
