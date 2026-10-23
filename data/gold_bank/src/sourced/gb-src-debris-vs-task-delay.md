---
id: gb-src-debris-vs-task-delay
category: docs-question
topics: Debris, AddItem, task.delay, Destroy, temporary instances, cleanup
source: adapted
source_id: creator-docs
source_path: content/en-us/reference/engine/classes/Debris.yaml
source_commit: 7400643072eb304fe85ef89cffe96f5c56f98c7e
---
# Request
For bullet holes and shell casings I've seen three ways to remove them after a few seconds: `task.wait(3) part:Destroy()`, `task.delay(3, ...)`, and `Debris:AddItem(part, 3)`. Which one should I use?

# Answer
Never `task.wait` in the code that spawns the effect: it blocks that thread for the whole lifetime. `task.delay(seconds, inst.Destroy, inst)` and `Debris:AddItem(inst, seconds)` both schedule the removal without blocking; `Debris` is the convenient choice for fire-and-forget effects and never errors if the instance is already gone, while `task.delay` returns a thread you can cancel if the object should live longer.

```lua
--!strict
local Debris = game:GetService("Debris")

local Effects = {}

function Effects.spawnCasing(template: BasePart, cframe: CFrame, lifetime: number): BasePart
	local casing = template:Clone()
	casing.CFrame = cframe
	casing.Parent = workspace
	Debris:AddItem(casing, lifetime)
	return casing
end

function Effects.spawnDecal(template: BasePart, cframe: CFrame, lifetime: number): (BasePart, thread)
	local mark = template:Clone()
	mark.CFrame = cframe
	mark.Parent = workspace
	local cleanup = task.delay(lifetime, mark.Destroy, mark)
	return mark, cleanup
end

function Effects.keep(mark: BasePart, cleanup: thread, extraLifetime: number): thread
	task.cancel(cleanup)
	return task.delay(extraLifetime, mark.Destroy, mark)
end

return Effects
```

- Both scheduled forms return immediately, so a weapon can spawn dozens of effects per second from one thread.
- Passing `mark.Destroy, mark` to `task.delay` avoids creating a closure per effect.
- Keep `task.cancel` for cases like "a decal stays while its wall is highlighted"; `Debris` has no way to cancel.

# Test
```lua
local template = Instance.new("Part")
local casing = item.spawnCasing(template, CFrame.new(0, 5, 0), 3)
local mark, cleanup = item.spawnDecal(template, CFrame.new(1, 1, 1), 2)
check("spawned in workspace without blocking", casing.Parent == workspace and mark.Parent == workspace)
__advance(2.1)
check("decal removed after its lifetime", mark.Parent == nil)
check("casing still present", casing.Parent == workspace)
__advance(1)
check("casing removed by Debris", casing.Parent == nil)
local kept, cleanup2 = item.spawnDecal(template, CFrame.new(), 1)
item.keep(kept, cleanup2, 5)
__advance(2)
check("cancelled cleanup keeps it longer", kept.Parent == workspace)
__advance(4)
check("removed after the extended lifetime", kept.Parent == nil and cleanup ~= nil)
```
