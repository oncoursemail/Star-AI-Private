---
id: gb-eng-export-type-shared-types
category: luau-typing
topics: export type, ModuleScript, shared types, require, type imports
source: original
---
# Request
Several of my scripts pass around the same "quest" table and each one redeclares the type, which drifts out of sync. How do I define the type once in a ModuleScript and use it from other scripts? I'd also like a constructor so quests are always built correctly.

# Answer
Put the types in one ModuleScript with `export type`, and give it a constructor that is the only place quest tables are built. Other scripts `require` it and refer to `QuestTypes.Quest`.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Shared.QuestTypes
export type QuestStatus = "Locked" | "Active" | "Completed"

export type Objective = {
	description: string,
	required: number,
	progress: number,
}

export type Quest = {
	id: string,
	title: string,
	status: QuestStatus,
	objectives: { Objective },
	rewardCoins: number,
}

local QuestTypes = {}

function QuestTypes.newQuest(id: string, title: string, rewardCoins: number, goals: { [string]: number }): Quest
	local objectives: { Objective } = {}
	for description, required in goals do
		table.insert(objectives, { description = description, required = math.max(1, required), progress = 0 })
	end
	table.sort(objectives, function(a: Objective, b: Objective): boolean
		return a.description < b.description
	end)
	return { id = id, title = title, status = "Locked", objectives = objectives, rewardCoins = rewardCoins }
end

function QuestTypes.isComplete(quest: Quest): boolean
	for _, objective in quest.objectives do
		if objective.progress < objective.required then
			return false
		end
	end
	return true
end

return QuestTypes
```

- In a consumer: `local QuestTypes = require(ReplicatedStorage.Shared.QuestTypes)`, then `type Quest = QuestTypes.Quest` and `local function addProgress(quest: Quest, amount: number)`. The alias is local; the source of truth stays in one file.
- The require path must be a static expression (`ReplicatedStorage.Shared.QuestTypes`, not a string built at runtime) or the analyzer cannot see the exported types.
- `QuestStatus` is a union of string literals, so `quest.status = "Done"` is rejected by the analyzer.
- Types are erased at runtime: exporting them costs nothing and does not add fields to the module table.

# Test
```lua
local q = item.newQuest("q1", "Gather", 50, { ["Collect wood"] = 3, ["Collect stone"] = 0 })
check("starts locked", q.status == "Locked")
check("objectives sorted", q.objectives[1].description == "Collect stone" and q.objectives[2].description == "Collect wood")
check("required clamps to at least 1", q.objectives[1].required == 1)
check("not complete initially", not item.isComplete(q))
q.objectives[1].progress = 1
q.objectives[2].progress = 3
check("complete when all met", item.isComplete(q))
```
