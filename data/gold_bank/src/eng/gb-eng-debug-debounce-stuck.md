---
id: gb-eng-debug-debounce-stuck
category: engineering-debugging
topics: debounce, early return, pcall, stuck flag, tool activation
source: original
---
# Request
My fireball tool works a few times and then stops responding until the player resets. No errors show unless I look closely; occasionally there's one from `findTarget`. Here's the handler:

```lua
local busy = false
tool.Activated:Connect(function()
	if busy then return end
	busy = true
	local target = findTarget()
	if not target then return end
	castFireball(target)
	task.wait(1.5)
	busy = false
end)
```

# Answer
The flag is set to `true`, but two paths leave without clearing it: the early `return` when there is no target, and any error thrown by `findTarget` or `castFireball`. After either one, `busy` stays true forever. Replace the boolean with a timestamp (a cooldown cannot get stuck) and run the risky work in `pcall` so an error is reported without breaking the tool.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Cooldown
export type Cooldown = { duration: number, readyAt: number }

local Cooldown = {}

function Cooldown.new(duration: number): Cooldown
	return { duration = duration, readyAt = 0 }
end

function Cooldown.tryUse(cd: Cooldown): boolean
	local now = os.clock()
	if now < cd.readyAt then
		return false
	end
	cd.readyAt = now + cd.duration
	return true
end

-- Runs action if off cooldown. A missing target refunds the cooldown; errors are reported, never left stuck.
function Cooldown.run(cd: Cooldown, action: () -> boolean): (boolean, string?)
	if not Cooldown.tryUse(cd) then
		return false, "cooldown"
	end
	local ok, result = pcall(action)
	if not ok then
		return false, tostring(result)
	end
	if result ~= true then
		cd.readyAt = 0 -- nothing happened (no target): let the player try again at once
		return false, "no effect"
	end
	return true, nil
end

return Cooldown
```

- Tool script: `local cd = Cooldown.new(1.5)` and `tool.Activated:Connect(function() local ok, why = Cooldown.run(cd, cast) if not ok and why ~= "cooldown" and why ~= "no effect" then warn(why) end end)`, where `cast` returns true when it fired.
- A timestamp has no "reset" step to forget: the cooldown simply expires, whatever path the code took.
- On the server, keep a cooldown per player for the remote that actually casts the fireball; a client-side cooldown only improves feel.

# Test
```lua
local cd = item.new(1.5)
local casts = 0
local function cast()
	casts += 1
	return true
end
check("first cast fires", item.run(cd, cast) == true and casts == 1)
check("blocked during cooldown", select(2, item.run(cd, cast)) == "cooldown" and casts == 1)
__advance(1.6)
local ok, err = item.run(cd, function()
	error("findTarget exploded", 0)
end)
check("error reported", not ok and err == "findTarget exploded")
__advance(1.6)
check("not stuck after an error", item.run(cd, cast) == true and casts == 2)
__advance(1.6)
local _, why = item.run(cd, function()
	return false
end)
check("no target refunds cooldown", why == "no effect" and item.run(cd, cast) == true and casts == 3)
```
