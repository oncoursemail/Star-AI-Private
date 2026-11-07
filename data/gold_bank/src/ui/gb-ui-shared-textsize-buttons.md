---
id: gb-ui-shared-textsize-buttons
category: ui-text
topics: TextScaled, UITextSizeConstraint, TextSize, consistent typography, AbsoluteSize
source: original
---
# Request
All my menu buttons use TextScaled. The result: "OK" is enormous, "Settings" is smaller, "Leaderboard" is tiny, and on tablets everything is huge. I want every button in a row to share the same readable text size that still adapts to the screen. Is TextScaled the wrong tool?

# Answer
TextScaled sizes each label on its own to fill its box, so short words get bigger text than long ones. For a group, compute one TextSize from the buttons' height (with a min and max) and the longest label's width budget, and apply it to all of them. Keep TextScaled with a UITextSizeConstraint only for single, standalone labels.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.GroupTextSize
local GroupTextSize = {}

export type Limits = { min: number, max: number, heightRatio: number, charWidth: number }

local DEFAULT: Limits = { min = 14, max = 24, heightRatio = 0.45, charWidth = 0.55 }

-- Largest size that fits the button height and the longest label in the available width.
function GroupTextSize.compute(buttonHeight: number, buttonWidth: number, longestChars: number, limits: Limits?): number
	local l = limits or DEFAULT
	local byHeight = buttonHeight * l.heightRatio
	local byWidth = if longestChars > 0 then buttonWidth / (longestChars * l.charWidth) else l.max
	return math.floor(math.clamp(math.min(byHeight, byWidth), l.min, l.max))
end

function GroupTextSize.apply(buttons: { TextButton }, limits: Limits?)
	if #buttons == 0 then
		return
	end
	local longest = 0
	for _, button in buttons do
		local text: string = button.Text
		longest = math.max(longest, utf8.len(text) or #text)
	end
	local size: Vector2 = buttons[1].AbsoluteSize
	local textSize = GroupTextSize.compute(size.Y, size.X, longest, limits)
	for _, button in buttons do
		button.TextScaled = false
		button.TextSize = textSize
		button.TextTruncate = Enum.TextTruncate.AtEnd
	end
end

function GroupTextSize.scaledLabel(label: TextLabel, minSize: number, maxSize: number)
	label.TextScaled = true
	local cap = label:FindFirstChildOfClass("UITextSizeConstraint") or Instance.new("UITextSizeConstraint")
	cap.MinTextSize = minSize
	cap.MaxTextSize = maxSize
	cap.Parent = label
end

return GroupTextSize
```

- `charWidth` is an average glyph width as a fraction of the text size; 0.55 suits most sans-serif fonts, raise it for wide display fonts.
- Re-run `apply` when the row's AbsoluteSize changes (rotation, window resize), not every frame.
- Truncation is the last resort if a translation is much longer than the English label.

# Test
```lua
check("height limits short labels", item.compute(50, 200, 2) == 22)
check("long labels shrink to fit width", item.compute(50, 120, 11) == 19)
check("never below the minimum", item.compute(20, 60, 30) == 14)
check("never above the maximum", item.compute(200, 800, 2) == 24)
local buttons = {}
for i, text in { "OK", "Settings", "Leaderboard" } do
	local b = Instance.new("TextButton")
	b.Text = text
	b.TextScaled = true
	b.AbsoluteSize = Vector2.new(160, 48)
	buttons[i] = b
end
item.apply(buttons)
check("all buttons share one size", buttons[1].TextSize == buttons[3].TextSize and buttons[2].TextSize == buttons[3].TextSize)
check("TextScaled turned off", buttons[1].TextScaled == false)
local label = Instance.new("TextLabel")
item.scaledLabel(label, 12, 28)
item.scaledLabel(label, 12, 30)
check("standalone label capped, constraint reused", label.UITextSizeConstraint.MaxTextSize == 30 and #label:GetChildren() == 1)
```
