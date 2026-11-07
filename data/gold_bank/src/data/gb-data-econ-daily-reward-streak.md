---
id: gb-data-econ-daily-reward-streak
category: economy-simulation
topics: daily reward, streak, server time, os.time, reward calendar
source: original
---
# Request
I want a 7-day daily reward calendar: claim once a day, the streak goes up each day you claim, and resets if you miss a day. My current version uses the client's clock and people just change their system time. How should it work?

# Answer
Use only server time (`os.time()` on the server) and store the last claim time and streak in the player's data. A claim is allowed 20 hours after the last one (so the daily time can drift), the streak continues if the claim comes within 48 hours, otherwise it resets to day 1; the reward comes from a server table indexed by the streak.

```lua
--!strict
-- ModuleScript: ServerScriptService.DailyReward
export type DailyData = { lastClaim: number, streak: number }
export type Claim = { ok: boolean, reward: number?, day: number?, waitSeconds: number? }

local MIN_GAP = 20 * 3600
local STREAK_WINDOW = 48 * 3600
local REWARDS = { 50, 75, 100, 150, 200, 300, 500 } -- day 1..7, then repeats

local DailyReward = {}

-- `now` is os.time() on the server; never a value from the client.
function DailyReward.claim(data: DailyData, now: number): Claim
	local elapsed = now - data.lastClaim
	if data.lastClaim > 0 and elapsed < MIN_GAP then
		return { ok = false, waitSeconds = MIN_GAP - math.max(elapsed, 0) }
	end
	local streak = if data.lastClaim > 0 and elapsed <= STREAK_WINDOW then data.streak + 1 else 1
	data.streak = streak
	data.lastClaim = now
	local day = (streak - 1) % #REWARDS + 1
	return { ok = true, reward = REWARDS[day], day = day }
end

-- For the UI: what the next claim will be and when.
function DailyReward.preview(data: DailyData, now: number): (number, number)
	local elapsed = now - data.lastClaim
	local continues = data.lastClaim > 0 and elapsed <= STREAK_WINDOW
	local nextStreak = if continues then data.streak + 1 else 1
	local readyIn = if data.lastClaim > 0 then math.max(0, MIN_GAP - elapsed) else 0
	return REWARDS[(nextStreak - 1) % #REWARDS + 1], readyIn
end

return DailyReward
```

The remote handler calls `DailyReward.claim(profile.daily, os.time())`, adds `reward` through the currency module when `ok`, and marks the profile dirty.

- Clock tricks on the client do nothing because the client never supplies a time; it only asks "claim".
- The 20-hour minimum with a 48-hour window lets a player who claims at 9 pm one day and 7 pm the next keep their streak.
- A server clock that jumps backwards makes `elapsed` negative, which simply reads as "not ready yet".

# Test
```lua
local day = 24 * 3600
local t0 = 1700000000
local data = { lastClaim = 0, streak = 0 }
local first = item.claim(data, t0)
check("first claim gives day 1", first.ok and first.day == 1 and first.reward == 50)
local early = item.claim(data, t0 + 3600)
check("claiming again too early is refused with a wait", not early.ok and early.waitSeconds == 19 * 3600)
local second = item.claim(data, t0 + 22 * 3600)
check("claim within the window continues the streak", second.ok and second.day == 2 and second.reward == 75)
local reward, readyIn = item.preview(data, t0 + 23 * 3600)
check("preview shows the next reward and wait", reward == 100 and readyIn == 19 * 3600)
local late = item.claim(data, t0 + 22 * 3600 + 3 * day)
check("missing a day resets the streak", late.ok and late.day == 1)
for i = 1, 7 do
	item.claim(data, t0 + 22 * 3600 + 3 * day + i * day)
end
check("calendar wraps after day 7", data.streak == 8 and item.preview(data, t0 + 22 * 3600 + 11 * day) == 75)
local skew = item.claim(data, data.lastClaim - 500)
check("a clock jump backwards is treated as not ready", not skew.ok)
```
