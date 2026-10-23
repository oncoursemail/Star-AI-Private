---
id: gb-world-round-win-conditions
category: round-systems
topics: win condition, last standing, team elimination, points, draw
source: original
---
# Request
My game has three modes: free-for-all last one standing, team elimination, and a timed mode where most points wins. I keep writing the win checks inline and they disagree about draws. Can you write one function that decides the result for any mode?

# Answer
Feed a plain snapshot of the participants (id, team, alive, points) and whether time ran out into one pure function. It returns nil while the round should continue, or a result describing the winning player, the winning team, or a draw. Because it is pure, every edge case (everyone dead, tied points) is decided the same way and can be tested.

```lua
--!strict
-- ModuleScript: ServerScriptService.WinConditions
export type Mode = "LastStanding" | "TeamElimination" | "MostPoints"
export type Participant = { id: number, team: string?, alive: boolean, points: number }
export type Result = { kind: "Player" | "Team" | "Draw", playerId: number?, team: string? }

local WinConditions = {}

local function lastStanding(participants: { Participant }, timeUp: boolean): Result?
	local survivors: { Participant } = {}
	for _, p in participants do
		if p.alive then
			table.insert(survivors, p)
		end
	end
	if #survivors == 1 then
		return { kind = "Player", playerId = survivors[1].id }
	elseif #survivors == 0 or timeUp then
		return { kind = "Draw" }
	end
	return nil
end

local function teamElimination(participants: { Participant }, timeUp: boolean): Result?
	local aliveTeams: { [string]: number } = {}
	local teamCount = 0
	local lastTeam: string? = nil
	for _, p in participants do
		if p.alive and p.team then
			if aliveTeams[p.team] == nil then
				aliveTeams[p.team] = 0
				teamCount += 1
				lastTeam = p.team
			end
			aliveTeams[p.team] += 1
		end
	end
	if teamCount == 1 then
		return { kind = "Team", team = lastTeam }
	elseif teamCount == 0 or timeUp then
		return { kind = "Draw" }
	end
	return nil
end

local function mostPoints(participants: { Participant }, timeUp: boolean): Result?
	if not timeUp then
		return nil
	end
	local best: Participant? = nil
	local tied = false
	for _, p in participants do
		if best == nil or p.points > best.points then
			best, tied = p, false
		elseif p.points == best.points then
			tied = true
		end
	end
	if best == nil or tied then
		return { kind = "Draw" }
	end
	return { kind = "Player", playerId = best.id }
end

function WinConditions.evaluate(mode: Mode, participants: { Participant }, timeUp: boolean): Result?
	if mode == "LastStanding" then
		return lastStanding(participants, timeUp)
	elseif mode == "TeamElimination" then
		return teamElimination(participants, timeUp)
	end
	return mostPoints(participants, timeUp)
end

return WinConditions
```

- The snapshot uses UserIds and team names, not Instances, so a player leaving mid-check cannot break it; build it from your roster right before calling.
- "Everyone died in the same explosion" is an explicit draw instead of a crash on `survivors[1]`.
- Ties for most points return a draw; if your game wants sudden death, check for a Draw result and extend the round instead of ending it.

# Test
```lua
local function p(id, team, alive, points)
	return { id = id, team = team, alive = alive, points = points or 0 }
end
check("round continues with several survivors", item.evaluate("LastStanding", { p(1, nil, true), p(2, nil, true) }, false) == nil)
local solo = item.evaluate("LastStanding", { p(1, nil, false), p(2, nil, true) }, false)
check("last one standing wins", solo ~= nil and solo.kind == "Player" and solo.playerId == 2)
check("everyone dead is a draw", item.evaluate("LastStanding", { p(1, nil, false), p(2, nil, false) }, false).kind == "Draw")
local team = item.evaluate("TeamElimination", { p(1, "Red", true), p(2, "Red", false), p(3, "Blue", false) }, false)
check("last team alive wins", team ~= nil and team.kind == "Team" and team.team == "Red")
check("teams alive at time-out draw", item.evaluate("TeamElimination", { p(1, "Red", true), p(3, "Blue", true) }, true).kind == "Draw")
check("points mode waits for the timer", item.evaluate("MostPoints", { p(1, nil, true, 5) }, false) == nil)
local top = item.evaluate("MostPoints", { p(1, nil, true, 5), p(2, nil, false, 9), p(3, nil, true, 2) }, true)
check("most points wins even if dead", top ~= nil and top.playerId == 2)
check("tied points draw", item.evaluate("MostPoints", { p(1, nil, true, 9), p(2, nil, true, 9) }, true).kind == "Draw")
```
