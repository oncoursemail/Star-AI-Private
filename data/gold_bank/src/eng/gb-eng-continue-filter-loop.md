---
id: gb-eng-continue-filter-loop
category: luau-syntax
topics: continue, guard clauses, loops, nested if, readability
source: original
---
# Request
My reward loop is five levels of nested `if`s and I can't follow it. Is there a `continue` in Luau? Here's the loop (server side, awards a daily bonus):

```lua
for _, player in Players:GetPlayers() do
	if player:GetAttribute("Loaded") then
		local last = player:GetAttribute("LastBonus")
		if last == nil or os.time() - last >= 86400 then
			if not player:GetAttribute("Banned") then
				local streak = player:GetAttribute("Streak") or 0
				player:SetAttribute("Streak", streak + 1)
				player:SetAttribute("LastBonus", os.time())
			end
		end
	end
end
```

# Answer
Yes: `continue` skips to the next iteration of the innermost loop. Turn each condition into a guard that continues early, and the actual work sits at one indentation level. The streak also needs a reset when a day was missed, which is easy to add once the loop is flat.

```lua
--!strict
-- ModuleScript: ServerScriptService.DailyBonus
local Players = game:GetService("Players")

local DAY = 86400

local DailyBonus = {}

function DailyBonus.award(now: number): { Player }
	local awarded: { Player } = {}
	for _, player in Players:GetPlayers() do
		if player:GetAttribute("Loaded") ~= true or player:GetAttribute("Banned") == true then
			continue
		end
		local last = player:GetAttribute("LastBonus")
		if type(last) == "number" and now - last < DAY then
			continue
		end
		local streak = player:GetAttribute("Streak")
		local missedADay = type(last) == "number" and now - last >= 2 * DAY
		local newStreak = if type(streak) == "number" and not missedADay then streak + 1 else 1
		player:SetAttribute("Streak", newStreak)
		player:SetAttribute("LastBonus", now)
		table.insert(awarded, player)
	end
	return awarded
end

return DailyBonus
```

- Like `break`, `continue` must be the last statement of its block. It is a contextual keyword, so old code with a variable named `continue` still compiles.
- Passing `now` in instead of calling `os.time()` inside makes the function testable and keeps every player in one pass on the same timestamp.
- Attributes only replicate from the server, so this belongs in a server script; the client just reads `Streak` for display.

# Test
```lua
local a = __makePlayer(1, "A")
local b = __makePlayer(2, "B")
local c = __makePlayer(3, "C")
local d = __makePlayer(4, "D")
a:SetAttribute("Loaded", true)
b:SetAttribute("Loaded", true)
b:SetAttribute("LastBonus", 1000)
b:SetAttribute("Streak", 4)
c:SetAttribute("Loaded", true)
c:SetAttribute("Banned", true)
d:SetAttribute("Loaded", false)
local now = 1000 + 86400 + 5
local got = item.award(now)
check("new player and due player awarded", #got == 2)
check("first bonus starts streak", a:GetAttribute("Streak") == 1)
check("streak continues next day", b:GetAttribute("Streak") == 5 and b:GetAttribute("LastBonus") == now)
check("banned and unloaded skipped", c:GetAttribute("Streak") == nil and d:GetAttribute("Streak") == nil)
check("not twice in a day", #item.award(now + 60) == 0)
check("missed day resets streak", #item.award(now + 3 * 86400) == 2 and b:GetAttribute("Streak") == 1)
```
