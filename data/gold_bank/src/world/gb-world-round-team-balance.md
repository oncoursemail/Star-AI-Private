---
id: gb-world-round-team-balance
category: round-systems
topics: team balancing, Teams, join order, auto assign, minimal moves
source: original
---
# Request
With AutoAssignable teams, after a few people leave I end up with 6 vs 2. Reshuffling everyone at round start annoys players whose friends were on their team. I want to move as few people as possible, and move the most recent joiners first.

# Answer
Track when each player joined, then rebalance by repeatedly moving the latest joiner from the largest team to the smallest until the sizes differ by at most one. New joiners go straight to the smallest team. Nobody who already sits on a balanced team is touched.

```lua
--!strict
-- ModuleScript: ServerScriptService.TeamBalance
local Players = game:GetService("Players")

local TeamBalance = {}

local joinOrder: { [Player]: number } = {}
local joinCounter = 0

local function track(player: Player)
	if joinOrder[player] == nil then
		joinCounter += 1
		joinOrder[player] = joinCounter
	end
end

function TeamBalance.smallest(teams: { Team }): Team
	local best = teams[1]
	for _, team in teams do
		if #team:GetPlayers() < #best:GetPlayers() then
			best = team
		end
	end
	return best
end

function TeamBalance.rebalance(teams: { Team }): number
	local moved = 0
	-- Each pass moves one player, so there can never be more passes than players.
	for _ = 1, #Players:GetPlayers() do
		local largest, smallest = teams[1], teams[1]
		for _, team in teams do
			local size = #team:GetPlayers()
			if size > #largest:GetPlayers() then
				largest = team
			end
			if size < #smallest:GetPlayers() then
				smallest = team
			end
		end
		if #largest:GetPlayers() - #smallest:GetPlayers() <= 1 then
			return moved
		end
		local latest: Player? = nil
		for _, player in largest:GetPlayers() do
			if latest == nil or (joinOrder[player] or 0) > (joinOrder[latest] or 0) then
				latest = player
			end
		end
		if latest == nil then
			return moved
		end
		latest.Team = smallest
		moved += 1
	end
	return moved
end

function TeamBalance.bind(teams: { Team })
	Players.PlayerAdded:Connect(function(player: Player)
		track(player)
		player.Team = TeamBalance.smallest(teams)
	end)
	Players.PlayerRemoving:Connect(function(player: Player)
		joinOrder[player] = nil
	end)
	for _, player in Players:GetPlayers() do
		track(player)
	end
end

return TeamBalance
```

Call `TeamBalance.bind({ Teams.Red, Teams.Blue })` once at startup and `TeamBalance.rebalance(...)` at the start of each round.

- Turn off `AutoAssignable` on the Team objects so the engine's assignment does not race with this module.
- Moving the latest joiners first means long-standing groups stay together; it is a cheap stand-in for party tracking.
- The loop moves one player per iteration and stops at a difference of one, so it performs the minimum number of moves.

# Test
```lua
local teams = game:GetService("Teams")
local red = Instance.new("Team")
red.Name = "Red"
red.Parent = teams
local blue = Instance.new("Team")
blue.Name = "Blue"
blue.Parent = teams
item.bind({ red, blue })

local players = {}
for i = 1, 8 do
	players[i] = __makePlayer(60 + i, "P" .. i)
end
check("joiners alternate to the smaller team", #red:GetPlayers() == 4 and #blue:GetPlayers() == 4)
for i = 1, 8 do
	if players[i].Team == blue and #blue:GetPlayers() > 1 then
		__removePlayer(players[i])
	end
end
check("leaving unbalances the teams", #red:GetPlayers() == 4 and #blue:GetPlayers() == 1)
local redBefore = red:GetPlayers()
local moved = item.rebalance({ red, blue })
check("minimal moves to balance", moved == 1 and #red:GetPlayers() == 3 and #blue:GetPlayers() == 2)
local latest = nil
for _, p in redBefore do
	if p.Team == blue then latest = p end
end
check("the most recent joiner was moved", latest == players[7])
check("balanced teams are left alone", item.rebalance({ red, blue }) == 0)
```
