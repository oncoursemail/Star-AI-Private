---
id: gb-data-remote-strikes-kick-vs-log
category: remote-security
topics: anti-exploit, kick, logging, false positives, strike decay
source: original
---
# Request
When a remote gets bad input, should I kick the player right away? I'm worried about kicking laggy players by mistake. How do people usually decide between logging and kicking?

# Answer
Score suspicious events instead of kicking on the first one. Input that an unmodified client can never produce (wrong types, NaN, Instances it cannot see) is strong evidence and weighs a lot; things lag can cause (requests slightly too fast, a distance check just over the limit) weigh little. Scores decay over time, and the player is kicked only when the score crosses a threshold.

```lua
--!strict
-- ModuleScript: ServerScriptService.Strikes
local Players = game:GetService("Players")

export type Severity = "lag" | "suspicious" | "impossible"
export type Strikes = {
	report: (player: Player, severity: Severity, reason: string) -> boolean,
	score: (player: Player) -> number,
}

local WEIGHTS: { [Severity]: number } = { lag = 1, suspicious = 3, impossible = 10 }

local Strikes = {}

function Strikes.new(kickAt: number, decayPerSecond: number, log: (string) -> ()): Strikes
	local scores: { [Player]: { value: number, updated: number } } = {}

	Players.PlayerRemoving:Connect(function(player: Player)
		scores[player] = nil
	end)

	local function current(player: Player): number
		local entry = scores[player]
		if entry == nil then
			return 0
		end
		local now = os.clock()
		entry.value = math.max(0, entry.value - (now - entry.updated) * decayPerSecond)
		entry.updated = now
		return entry.value
	end

	-- Returns true when this report got the player kicked.
	local function report(player: Player, severity: Severity, reason: string): boolean
		local value = current(player) + WEIGHTS[severity]
		scores[player] = { value = value, updated = os.clock() }
		log(string.format("%d %s %s (score %.1f)", player.UserId, severity, reason, value))
		if value >= kickAt then
			player:Kick("Unexpected network activity. Please rejoin.")
			return true
		end
		return false
	end

	return { report = report, score = current }
end

return Strikes
```

Usage in a handler: `if type(slot) ~= "number" then strikes.report(player, "impossible", "slot type") return end`, and `strikes.report(player, "lag", "fire rate")` when a cooldown check fails.

- Always reject the bad request itself, whatever the score; the score only decides whether to also remove the player.
- The kick message stays neutral; telling exploiters which check fired helps them tune around it.
- Send the log lines to your analytics or a webhook proxy and review them before tightening weights; logs show which checks have false positives.

# Test
```lua
local lines = {}
local strikes = item.new(10, 0.1, function(line)
	table.insert(lines, line)
end)
local laggy = __makePlayer(1, "Laggy")
for _ = 1, 5 do
	strikes.report(laggy, "lag", "fire rate")
end
check("a few lag events do not kick", laggy.__kicked == nil and strikes.score(laggy) == 5)
check("every event is logged", #lines == 5)

__advance(30)
check("scores decay over time", math.abs(strikes.score(laggy) - 2) < 1e-6)

local cheater = __makePlayer(2, "Cheater")
local kicked = strikes.report(cheater, "impossible", "NaN amount")
check("impossible input kicks immediately", kicked and cheater.__kicked ~= nil)

local borderline = __makePlayer(3, "Borderline")
strikes.report(borderline, "suspicious", "distance")
strikes.report(borderline, "suspicious", "distance")
strikes.report(borderline, "suspicious", "distance")
check("three suspicious events stay under the threshold", borderline.__kicked == nil)
strikes.report(borderline, "lag", "rate")
check("and one more crosses it", borderline.__kicked ~= nil)
```
