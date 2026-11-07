---
id: gb-ui-tab-bar-bumpers
category: ui-interaction
topics: tab bar, pages, ContextActionService, ButtonL1 ButtonR1, selected state
source: original
---
# Request
My menu has tabs (Items, Pets, Upgrades) as buttons along the top and a page for each. I'm toggling `Visible` on pages in three separate click handlers and it's getting messy. I'd also like controller players to switch tabs with the bumpers. How would you structure it?

# Answer
Hold the tabs in an ordered list and keep one `select(index)` that updates every tab's look and every page's visibility from the selected index. Clicks call `select`; the bumpers (and Q/E on keyboard) step through the list with wrap-around, bound only while the menu is open.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.TabBar
local ContextActionService = game:GetService("ContextActionService")

local TabBar = {}

export type Tab = { button: TextButton, page: GuiObject }
export type Bar = {
	select: (index: number) -> (),
	selected: () -> number,
	bindKeys: () -> (),
	unbindKeys: () -> (),
}

local ACTIVE = Color3.fromRGB(46, 120, 220)
local INACTIVE = Color3.fromRGB(44, 47, 55)
local ACTION = "TabBarStep"

function TabBar.new(tabs: { Tab }): Bar
	assert(#tabs > 0, "need at least one tab")
	local current = 1

	local function select(index: number)
		current = (index - 1) % #tabs + 1
		for i, tab in tabs do
			local on = i == current
			tab.page.Visible = on
			tab.button.BackgroundColor3 = if on then ACTIVE else INACTIVE
			local face = tab.button.FontFace
			tab.button.FontFace = Font.new(face.Family, if on then Enum.FontWeight.Bold else Enum.FontWeight.Regular, face.Style)
		end
	end

	for i, tab in tabs do
		local connection = tab.button.Activated:Connect(function()
			select(i)
		end)
		tab.button.Destroying:Once(function()
			connection:Disconnect()
		end)
	end

	local function onStep(_name: string, state: Enum.UserInputState, input: InputObject): Enum.ContextActionResult
		if state ~= Enum.UserInputState.Begin then
			return Enum.ContextActionResult.Pass
		end
		local back = input.KeyCode == Enum.KeyCode.ButtonL1 or input.KeyCode == Enum.KeyCode.Q
		select(current + (if back then -1 else 1))
		return Enum.ContextActionResult.Sink
	end

	select(1)
	return {
		select = select,
		selected = function()
			return current
		end,
		bindKeys = function()
			ContextActionService:BindAction(ACTION, onStep, false,
				Enum.KeyCode.ButtonL1, Enum.KeyCode.ButtonR1, Enum.KeyCode.Q, Enum.KeyCode.E)
		end,
		unbindKeys = function()
			ContextActionService:UnbindAction(ACTION)
		end,
	}
end

return TabBar
```

- Wrap-around (`(index - 1) % #tabs + 1`) means R1 on the last tab goes to the first, which is what console players expect.
- A bold weight plus the accent fill marks the active tab, so the state is not shown by colour alone.
- Bind the keys when the menu opens and unbind on close, or Q and E would switch tabs during gameplay.

# Test
```lua
local CAS = game:GetService("ContextActionService")
local tabs = {}
for i, name in { "Items", "Pets", "Upgrades" } do
	local b = Instance.new("TextButton")
	b.Name = name
	b.FontFace = Font.new("rbxasset://fonts/families/SourceSansPro.json")
	local page = Instance.new("Frame")
	tabs[i] = { button = b, page = page }
end
local bar = item.new(tabs)
check("first tab selected at start", bar.selected() == 1 and tabs[1].page.Visible and not tabs[2].page.Visible)
tabs[3].button.Activated:Fire()
check("click selects its page only", bar.selected() == 3 and tabs[3].page.Visible and not tabs[1].page.Visible)
check("active tab is bold", tabs[3].button.FontFace.Weight == Enum.FontWeight.Bold and tabs[1].button.FontFace.Weight == Enum.FontWeight.Regular)
bar.bindKeys()
local step = CAS.__bound.TabBarStep.fn
step("TabBarStep", Enum.UserInputState.Begin, { KeyCode = Enum.KeyCode.ButtonR1 })
check("R1 wraps from last to first", bar.selected() == 1)
step("TabBarStep", Enum.UserInputState.Begin, { KeyCode = Enum.KeyCode.ButtonL1 })
check("L1 wraps from first to last", bar.selected() == 3)
step("TabBarStep", Enum.UserInputState.End, { KeyCode = Enum.KeyCode.ButtonL1 })
check("release ignored", bar.selected() == 3)
bar.unbindKeys()
check("keys unbound on close", CAS.__bound.TabBarStep == nil)
```
