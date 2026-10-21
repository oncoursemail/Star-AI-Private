---
id: gb-eng-debug-destroyed-enemy-refs
category: engineering-debugging
topics: Destroy, stale references, memory leak, Destroying event, registry
source: original
---
# Request
I keep a table of active enemies for my targeting code. After a few waves the turret starts shooting at nothing, and the table keeps growing. I do destroy the enemy models when they die:

```lua
local enemies = {}

local function spawnEnemy(template)
	local model = template:Clone()
	model.Parent = workspace.Enemies
	table.insert(enemies, model)
	model.Humanoid.Died:Connect(function()
		task.wait(2)
		model:Destroy()
	end)
end
```

# Answer
`Destroy` removes the model from the game and locks it, but it cannot remove your references: the model stays in `enemies`, so the turret still sees it (its parts keep their last position) and the Lua table keeps every dead model alive in memory. Make the registry remove entries itself when the instance is destroyed, and treat a dead enemy as gone immediately rather than after the 2-second corpse delay.

```lua
--!strict
-- ModuleScript: ServerScriptService.EnemyRegistry
local EnemyRegistry = {}

local active: { [Model]: boolean } = {}

function EnemyRegistry.add(model: Model): ()
	local humanoid = model:FindFirstChildOfClass("Humanoid")
	if humanoid == nil then
		return
	end
	active[model] = true
	humanoid.Died:Once(function()
		active[model] = nil -- stop targeting at the moment of death
		task.delay(2, function()
			model:Destroy()
		end)
	end)
	model.Destroying:Once(function()
		active[model] = nil -- also covers models removed by other code
	end)
end

function EnemyRegistry.list(): { Model }
	local out: { Model } = {}
	for model in active do
		if model.Parent ~= nil then
			table.insert(out, model)
		end
	end
	return out
end

function EnemyRegistry.count(): number
	local n = 0
	for _ in active do
		n += 1
	end
	return n
end

return EnemyRegistry
```

- A set keyed by the model makes removal O(1); with an array you would have to search for the model before removing it.
- `Destroying` fires for any destroy path (round cleanup, a `ClearAllChildren`, an admin command), so the registry stays correct even when the death handler never runs.
- The `model.Parent ~= nil` check in `list` also skips models that were only unparented, not destroyed.

# Test
```lua
local function makeEnemy()
	local m = Instance.new("Model")
	local h = Instance.new("Humanoid")
	h.Parent = m
	m.Parent = workspace
	return m, h
end
local a, ha = makeEnemy()
local b = makeEnemy()
local c = makeEnemy()
item.add(a)
item.add(b)
item.add(c)
check("three active", item.count() == 3 and #item.list() == 3)
ha.Health = 0
check("dead enemy untargetable immediately", #item.list() == 2 and item.count() == 2)
__advance(2.5)
check("corpse destroyed after delay", a.Parent == nil)
b:Destroy()
check("destroyed by other code removed", item.count() == 1 and item.list()[1] == c)
local noHumanoid = Instance.new("Model")
noHumanoid.Parent = workspace
item.add(noHumanoid)
check("models without humanoid ignored", item.count() == 1)
```
