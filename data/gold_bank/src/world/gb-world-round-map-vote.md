---
id: gb-world-round-map-vote
category: round-systems
topics: map vote, RemoteEvent validation, tally, tie break, intermission
source: original
---
# Request
During intermission players vote for the next map by clicking buttons. The client fires `VoteRemote:FireServer(mapName)`. How do I make the server side safe (one vote each, only real options) and pick the winner fairly when there's a tie?

# Answer
Hold the vote on the server as a map from player to choice. A vote is accepted only if it is one of the offered option strings, re-voting replaces the old vote, and leaving removes it. The winner is the option with most votes, ties broken randomly, and an empty vote picks randomly among all options.

```lua
--!strict
-- ModuleScript: ServerScriptService.MapVote
local Players = game:GetService("Players")

export type Vote = {
	cast: (player: Player, choice: any) -> boolean,
	tally: () -> { [string]: number },
	winner: (random: Random) -> string,
	close: () -> (),
}

local MapVote = {}

function MapVote.new(options: { string }): Vote
	assert(#options > 0, "a vote needs at least one option")
	local votes: { [Player]: string } = {}
	local open = true
	local valid: { [string]: boolean } = {}
	for _, option in options do
		valid[option] = true
	end

	local removing = Players.PlayerRemoving:Connect(function(player: Player)
		votes[player] = nil
	end)

	local function tally(): { [string]: number }
		local counts: { [string]: number } = {}
		for _, option in options do
			counts[option] = 0
		end
		for _, choice in votes do
			counts[choice] += 1
		end
		return counts
	end

	return {
		cast = function(player: Player, choice: any): boolean
			if not open or type(choice) ~= "string" or not valid[choice] then
				return false
			end
			votes[player] = choice
			return true
		end,
		tally = tally,
		winner = function(random: Random): string
			local counts = tally()
			local best = -1
			local leaders: { string } = {}
			for _, option in options do
				if counts[option] > best then
					best = counts[option]
					leaders = { option }
				elseif counts[option] == best then
					table.insert(leaders, option)
				end
			end
			return leaders[random:NextInteger(1, #leaders)]
		end,
		close = function()
			open = false
			removing:Disconnect()
		end,
	}
end

return MapVote
```

Wiring the remote during intermission:

```lua
--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local MapVote = require(script.Parent:WaitForChild("MapVote"))

local voteRemote = ReplicatedStorage:WaitForChild("MapVoteRemote")

local function runVote(options: { string }, seconds: number): string
	local vote = MapVote.new(options)
	ReplicatedStorage:SetAttribute("VoteOptions", table.concat(options, ","))
	local connection = voteRemote.OnServerEvent:Connect(function(player: Player, choice: any)
		vote.cast(player, choice)
	end)
	task.wait(seconds)
	connection:Disconnect()
	vote.close()
	return vote.winner(Random.new())
end

return runVote
```

- Options are compared against the server's own list, so a client sending "AdminMap" or a table gets nothing.
- Keying votes by Player makes "one vote each" automatic, and changing your mind just overwrites your entry.
- Iterating `options` (an array) instead of the counts table keeps the order deterministic, so with a seeded Random the tie-break is reproducible.

# Test
```lua
local vote = item.new({ "Desert", "Forest", "Castle" })
local a, b, c = __makePlayer(71, "A"), __makePlayer(72, "B"), __makePlayer(73, "C")
check("valid vote accepted", vote.cast(a, "Forest"))
check("unknown map and wrong types rejected", not vote.cast(b, "AdminMap") and not vote.cast(b, { "Forest" }) and not vote.cast(b, nil))
vote.cast(b, "Castle")
vote.cast(b, "Forest")
check("re-voting replaces the old vote", vote.tally().Forest == 2 and vote.tally().Castle == 0)
check("most votes wins", vote.winner(Random.new(1)) == "Forest")
vote.cast(c, "Desert")
__removePlayer(a)
check("leaving removes the vote", vote.tally().Forest == 1)
local seen = {}
for seed = 1, 30 do
	seen[vote.winner(Random.new(seed * 104729))] = true
end
check("ties are broken between the leaders only", seen.Forest and seen.Desert and not seen.Castle)
vote.close()
check("closed vote rejects new votes", not vote.cast(c, "Castle"))
```
