---
id: gb-world-round-roster
category: round-systems
topics: alive players, join mid-round, leave mid-round, Died, elimination
source: original
---
# Request
In my elimination game I keep a table of alive players. Players who join mid-round get counted as alive, players who leave stay in the table forever, and the round never ends. How do I keep the participant list correct?

# Answer
Own the roster in one module: a round starts with the players present at that moment, joiners become spectators until the next round, and death or leaving removes a participant. Every removal goes through one function that fires a callback with the remaining count, so the win check runs exactly when it can change.

```lua
--!strict
-- ModuleScript: ServerScriptService.RoundRoster
local Players = game:GetService("Players")

export type Roster = {
	startRound: () -> number,
	endRound: () -> (),
	isAlive: (player: Player) -> boolean,
	alive: () -> { Player },
}

local RoundRoster = {}

function RoundRoster.new(onAliveChanged: (remaining: number) -> ()): Roster
	local alive: { [Player]: boolean } = {}
	local deathConnections: { [Player]: RBXScriptConnection } = {}
	local running = false

	local function count(): number
		local n = 0
		for _ in alive do
			n += 1
		end
		return n
	end

	local function eliminate(player: Player)
		if not alive[player] then
			return
		end
		alive[player] = nil
		local connection = deathConnections[player]
		if connection then
			connection:Disconnect()
			deathConnections[player] = nil
		end
		onAliveChanged(count())
	end

	local function endRound()
		running = false
		for _, connection in deathConnections do
			connection:Disconnect()
		end
		table.clear(deathConnections)
		table.clear(alive)
	end

	local function startRound(): number
		endRound()
		running = true
		for _, player in Players:GetPlayers() do
			local character = player.Character
			local humanoid = if character then character:FindFirstChildOfClass("Humanoid") else nil
			if humanoid and humanoid.Health > 0 then
				alive[player] = true
				deathConnections[player] = humanoid.Died:Connect(function()
					eliminate(player)
				end)
			end
		end
		return count()
	end

	Players.PlayerRemoving:Connect(function(player: Player)
		if running then
			eliminate(player)
		end
	end)

	return {
		startRound = startRound,
		endRound = endRound,
		isAlive = function(player: Player): boolean
			return alive[player] == true
		end,
		alive = function(): { Player }
			local list = {}
			for player in alive do
				table.insert(list, player)
			end
			return list
		end,
	}
end

return RoundRoster
```

- Joiners are never added during a round because only `startRound` adds players; they simply spawn in the lobby and play next round.
- The Died connection is per participant and per round, and it is disconnected on elimination, so respawned characters do not eliminate the player twice.
- Leaving is handled through `PlayerRemoving`, which fires before the character is destroyed, so the count drops immediately.
- In `onAliveChanged`, end the round when `remaining <= 1` (last player standing) or use your own condition.

# Test
```lua
local remaining = {}
local roster = item.new(function(n)
	table.insert(remaining, n)
end)
local a = __makePlayer(51, "A")
__makeCharacter(a)
local b = __makePlayer(52, "B")
local bChar = __makeCharacter(b)
local c = __makePlayer(53, "C")
__makeCharacter(c)

check("round starts with everyone alive", roster.startRound() == 3)
local late = __makePlayer(54, "Late")
__makeCharacter(late)
check("mid-round joiner is not a participant", not roster.isAlive(late) and #roster.alive() == 3)
bChar.Humanoid.Health = 0
check("death eliminates", not roster.isAlive(b) and remaining[#remaining] == 2)
__makeCharacter(b)
check("respawning does not revive", not roster.isAlive(b))
__removePlayer(c)
check("leaving eliminates", remaining[#remaining] == 1 and #roster.alive() == 1 and roster.isAlive(a))
roster.endRound()
check("next round includes the late joiner", roster.startRound() == 3 and roster.isAlive(late))
```
