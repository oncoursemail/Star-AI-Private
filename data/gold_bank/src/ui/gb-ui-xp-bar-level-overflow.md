---
id: gb-ui-xp-bar-level-overflow
category: ui-style
topics: progress bar, XP, level curve, fraction, overflow across levels
source: original
---
# Request
My XP bar takes total XP and a level curve where each level needs more XP. When a player gains enough XP to jump two levels at once, my bar shows more than 100% and the level text is wrong. How should I compute level and bar fill from total XP?

# Answer
Walk the curve: subtract each level's requirement from the total until the remainder is smaller than the next requirement. That gives the level, the XP into the current level and the requirement, so the fill is always between 0 and 1 no matter how many levels were gained at once. Keep it pure and let the bar render the result.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.LevelProgress
local LevelProgress = {}

export type Progress = { level: number, into: number, needed: number, fraction: number }

local MAX_LEVEL = 100

function LevelProgress.requirement(level: number): number
	return math.floor(100 * level ^ 1.5)
end

function LevelProgress.fromTotal(totalXp: number): Progress
	local remaining = math.max(0, math.floor(totalXp))
	local level = 1
	while level < MAX_LEVEL and remaining >= LevelProgress.requirement(level) do
		remaining -= LevelProgress.requirement(level)
		level += 1
	end
	if level >= MAX_LEVEL then
		return { level = MAX_LEVEL, into = 0, needed = 0, fraction = 1 }
	end
	local needed = LevelProgress.requirement(level)
	return { level = level, into = remaining, needed = needed, fraction = remaining / needed }
end

function LevelProgress.render(fill: Frame, label: TextLabel, totalXp: number)
	local p = LevelProgress.fromTotal(totalXp)
	fill.Size = UDim2.fromScale(p.fraction, 1)
	label.Text = if p.needed > 0
		then string.format("Level %d  %d / %d XP", p.level, p.into, p.needed)
		else string.format("Level %d  MAX", p.level)
end

return LevelProgress
```

- The loop runs at most MAX_LEVEL times, so even a corrupted huge XP value cannot hang the client.
- The server stores only total XP; level is derived the same way on both sides, so they can never disagree.
- For a level-up animation, tween the fill to 1, reset it to 0, then tween to the new fraction.

# Test
```lua
check("requirement grows", item.requirement(1) == 100 and item.requirement(4) == 800)
local p = item.fromTotal(50)
check("half of level 1", p.level == 1 and p.fraction == 0.5)
p = item.fromTotal(100 + 282 + 100)
check("two levels gained at once", p.level == 3 and p.into == 100 and p.needed == 519)
check("fraction stays within 0..1", p.fraction >= 0 and p.fraction < 1)
check("negative xp treated as zero", item.fromTotal(-20).level == 1 and item.fromTotal(-20).into == 0)
check("capped at max level", item.fromTotal(1e12).level == 100 and item.fromTotal(1e12).fraction == 1)
local fill, label = Instance.new("Frame"), Instance.new("TextLabel")
item.render(fill, label, 150)
check("renders bar and text", fill.Size.X.Scale == 50 / 282 and label.Text == "Level 2  50 / 282 XP")
```
