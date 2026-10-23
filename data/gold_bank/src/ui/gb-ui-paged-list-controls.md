---
id: gb-ui-paged-list-controls
category: ui-overflow
topics: pagination, page count, prev next buttons, Interactable, list slicing
source: original
---
# Request
For my trading post I'd rather show listings in pages of 12 than one endless scroll. I need "Page 2 of 7", previous/next buttons that disable at the ends, and the page to stay valid when listings disappear while someone is browsing.

# Answer
Keep the page as a number and derive everything else: page count from the total, the slice for the current page, and the button states. Clamp the page whenever the data changes, so a shrinking list can never leave the player on a page that no longer exists.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Pager
local Pager = {}

export type Pager = {
	setItems: (items: { string }) -> (),
	go: (delta: number) -> (),
	page: () -> number,
}

function Pager.pageCount(total: number, perPage: number): number
	return math.max(1, math.ceil(total / perPage))
end

function Pager.slice(items: { string }, page: number, perPage: number): { string }
	local out = {}
	for i = (page - 1) * perPage + 1, math.min(#items, page * perPage) do
		table.insert(out, items[i])
	end
	return out
end

local function setEnabled(button: GuiButton, enabled: boolean)
	button.Interactable = enabled
	button.BackgroundTransparency = if enabled then 0 else 0.6
end

function Pager.new(perPage: number, prev: GuiButton, nextButton: GuiButton, label: TextLabel, render: (pageItems: { string }) -> ()): Pager
	local items: { string } = {}
	local page = 1

	local function refresh()
		local count = Pager.pageCount(#items, perPage)
		page = math.clamp(page, 1, count)
		label.Text = string.format("Page %d of %d", page, count)
		setEnabled(prev, page > 1)
		setEnabled(nextButton, page < count)
		render(Pager.slice(items, page, perPage))
	end

	local function go(delta: number)
		page += delta
		refresh()
	end

	prev.Activated:Connect(function()
		go(-1)
	end)
	nextButton.Activated:Connect(function()
		go(1)
	end)

	return {
		setItems = function(newItems: { string })
			items = newItems
			refresh()
		end,
		go = go,
		page = function()
			return page
		end,
	}
end

return Pager
```

- `Interactable = false` stops clicks and gamepad activation; the faded background tells players why.
- An empty list still reports "Page 1 of 1", which reads better than "Page 1 of 0".
- Fetch pages from the server lazily if the full listing is large; the same clamp applies to the server's total.

# Test
```lua
check("page count rounds up", item.pageCount(80, 12) == 7 and item.pageCount(0, 12) == 1)
local data = {}
for i = 1, 30 do
	data[i] = "L" .. i
end
check("slice of a middle page", table.concat(item.slice(data, 2, 12), ",", 1, 2) == "L13,L14")
check("last page is partial", #item.slice(data, 3, 12) == 6)
local prev, nxt, label = Instance.new("TextButton"), Instance.new("TextButton"), Instance.new("TextLabel")
local shown = {}
local pager = item.new(12, prev, nxt, label, function(rows)
	shown = rows
end)
pager.setItems(data)
check("first page disables prev", label.Text == "Page 1 of 3" and prev.Interactable == false and nxt.Interactable == true)
nxt.Activated:Fire()
nxt.Activated:Fire()
check("last page disables next", pager.page() == 3 and nxt.Interactable == false and #shown == 6)
local fewer = {}
for i = 1, 10 do
	fewer[i] = "L" .. i
end
pager.setItems(fewer)
check("shrinking data clamps the page", pager.page() == 1 and label.Text == "Page 1 of 1")
```
