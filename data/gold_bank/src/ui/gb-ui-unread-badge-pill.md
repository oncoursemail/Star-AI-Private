---
id: gb-ui-unread-badge-pill
category: ui-text
topics: notification badge, 99+, AutomaticSize, UICorner pill, count label
source: original
---
# Request
I want a small red unread badge on my Quests button: a circle with a single digit, a pill that widens for "12", capped at "99+", and hidden when the count is zero. Mine is a fixed square, so two digits overflow.

# Answer
Make the badge a label with `AutomaticSize = X`, a fixed height, a UISizeConstraint whose minimum width equals the height (so one digit stays a circle), horizontal padding, and a fully rounded UICorner. A pure function turns the count into the text (or nil to hide).

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Badge
local Badge = {}

local HEIGHT = 20

export type BadgeHandle = { label: TextLabel, setCount: (count: number) -> () }

function Badge.text(count: number, cap: number?): string?
	local limit = cap or 99
	if count ~= count or count < 1 then
		return nil
	end
	local whole = math.floor(count)
	return if whole > limit then tostring(limit) .. "+" else tostring(whole)
end

function Badge.attach(target: GuiObject): BadgeHandle
	local label = Instance.new("TextLabel")
	label.Name = "Badge"
	label.AnchorPoint = Vector2.new(0.5, 0.5)
	label.Position = UDim2.new(1, -4, 0, 4)
	label.Size = UDim2.fromOffset(0, HEIGHT)
	label.AutomaticSize = Enum.AutomaticSize.X
	label.BackgroundColor3 = Color3.fromRGB(214, 48, 49)
	label.TextColor3 = Color3.new(1, 1, 1)
	label.TextSize = 13
	label.ZIndex = 5
	label.Visible = false

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0.5, 0)
	corner.Parent = label

	local minimum = Instance.new("UISizeConstraint")
	minimum.MinSize = Vector2.new(HEIGHT, HEIGHT)
	minimum.Parent = label

	local padding = Instance.new("UIPadding")
	padding.PaddingLeft = UDim.new(0, 6)
	padding.PaddingRight = UDim.new(0, 6)
	padding.Parent = label

	label.Parent = target

	return {
		label = label,
		setCount = function(count: number)
			local text = Badge.text(count)
			label.Visible = text ~= nil
			label.Text = text or ""
		end,
	}
end

return Badge
```

- Anchoring the badge at its centre on the button's top-right corner keeps it in place as it widens.
- A corner radius of 0.5 scale rounds the short side completely, giving a circle at minimum width and a pill beyond.
- White on this red is above 4.5:1 contrast, so the digits stay readable at small sizes.

# Test
```lua
check("hidden at zero", item.text(0) == nil)
check("single digit", item.text(7) == "7")
check("capped", item.text(250) == "99+")
check("custom cap", item.text(12, 9) == "9+")
check("NaN hidden", item.text(0 / 0) == nil)
local button = Instance.new("TextButton")
local badge = item.attach(button)
badge.setCount(3)
check("visible with text", badge.label.Visible and badge.label.Text == "3")
check("widens with content, circle minimum", badge.label.AutomaticSize == Enum.AutomaticSize.X
	and badge.label.UISizeConstraint.MinSize.X == 20)
badge.setCount(0)
check("hides again at zero", badge.label.Visible == false)
```
