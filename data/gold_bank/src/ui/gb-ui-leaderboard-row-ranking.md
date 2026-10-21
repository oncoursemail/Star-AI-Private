---
id: gb-ui-leaderboard-row-ranking
category: ui-layout
topics: UIListLayout, LayoutOrder, leaderboard, row reuse, sorting
source: original
---
# Request
I have a custom round scoreboard. Every second I `ClearAllChildren()` the list and rebuild every row from the scores table, which flickers and resets hover states. How can I update it so rows stay put and just reorder when scores change?

# Answer
Keep one row per player keyed by UserId, update its text in place, and let the UIListLayout order rows by `LayoutOrder` set to the rank. Rows for players that are gone are destroyed. Sorting uses a deterministic tie-break so equal scores do not swap places every update.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Scoreboard
local Scoreboard = {}

export type Entry = { userId: number, name: string, score: number }
export type Board = {
	update: (entries: { Entry }) -> (),
	rowFor: (userId: number) -> TextLabel?,
}

function Scoreboard.rank(entries: { Entry }): { Entry }
	local sorted: { Entry } = {}
	for i, entry in entries do
		sorted[i] = entry
	end
	table.sort(sorted, function(a: Entry, b: Entry): boolean
		if a.score ~= b.score then
			return a.score > b.score
		end
		return a.userId < b.userId
	end)
	return sorted
end

function Scoreboard.new(list: GuiObject): Board
	local rows: { [number]: TextLabel } = {}

	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.Padding = UDim.new(0, 2)
	layout.Parent = list

	local function update(entries: { Entry })
		local seen: { [number]: boolean } = {}
		for rank, entry in Scoreboard.rank(entries) do
			seen[entry.userId] = true
			local row = rows[entry.userId]
			if row == nil then
				local newRow = Instance.new("TextLabel")
				newRow.Name = tostring(entry.userId)
				newRow.Size = UDim2.new(1, 0, 0, 28)
				newRow.BackgroundTransparency = 1
				newRow.TextXAlignment = Enum.TextXAlignment.Left
				newRow.TextColor3 = Color3.fromRGB(235, 235, 240)
				newRow.TextSize = 16
				newRow.Parent = list
				rows[entry.userId] = newRow
				row = newRow
			end
			assert(row)
			row.LayoutOrder = rank
			row.Text = string.format("%d. %s  %d", rank, entry.name, entry.score)
		end
		for userId, row in rows do
			if not seen[userId] then
				row:Destroy()
				rows[userId] = nil
			end
		end
	end

	return {
		update = update,
		rowFor = function(userId: number): TextLabel?
			return rows[userId]
		end,
	}
end

return Scoreboard
```

- Rows are never recreated for existing players, so nothing flickers and a row being hovered keeps its state.
- Ties fall back to UserId; any stable key works, the point is that equal scores do not shuffle between updates.
- Removing entries while iterating with `pairs`-style generalised iteration is allowed for the current key, which is what the cleanup loop does.

# Test
```lua
local list = Instance.new("Frame")
local board = item.new(list)
board.update({
	{ userId = 1, name = "Ava", score = 10 },
	{ userId = 2, name = "Ben", score = 30 },
	{ userId = 3, name = "Cy", score = 20 },
})
check("highest score first", board.rowFor(2).LayoutOrder == 1 and board.rowFor(1).LayoutOrder == 3)
local avaRow = board.rowFor(1)
board.update({
	{ userId = 1, name = "Ava", score = 50 },
	{ userId = 2, name = "Ben", score = 30 },
})
check("rows are reused, not rebuilt", board.rowFor(1) == avaRow and avaRow.LayoutOrder == 1)
check("text updated in place", avaRow.Text == "1. Ava  50")
check("departed player row removed", board.rowFor(3) == nil and list:FindFirstChild("3") == nil)
local tied = item.rank({ { userId = 9, name = "Z", score = 5 }, { userId = 4, name = "Y", score = 5 } })
check("ties broken by user id", tied[1].userId == 4)
```
