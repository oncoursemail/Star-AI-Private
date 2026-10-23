---
id: gb-ui-stroke-border-mode
category: ui-style
topics: UIStroke, ApplyStrokeMode, UICorner, selected state, restrained styling
source: original
---
# Request
I added a UIStroke to my inventory slot buttons to get a border, but now the item count text also has a thick outline and looks blurry. I also want the selected slot to stand out without making everything glow. What am I doing wrong?

# Answer
On a TextButton or TextLabel, a UIStroke outlines the text by default (`ApplyStrokeMode.Contextual`). Set `ApplyStrokeMode = Border` to stroke the box instead. Keep the default border subtle (1 px, low contrast) and show selection by changing only the stroke colour and thickness, one restrained cue rather than glow plus gradient plus scale.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.SlotStyle
local SlotStyle = {}

local IDLE_STROKE = Color3.fromRGB(64, 68, 78)
local SELECTED_STROKE = Color3.fromRGB(90, 160, 255)

export type Slot = { button: TextButton, setSelected: (selected: boolean) -> () }

function SlotStyle.style(button: TextButton): Slot
	button.AutoButtonColor = false
	button.BackgroundColor3 = Color3.fromRGB(32, 34, 40)
	button.BorderSizePixel = 0
	button.TextColor3 = Color3.fromRGB(236, 236, 240)

	local corner = button:FindFirstChildOfClass("UICorner") or Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 6)
	corner.Parent = button

	local stroke = button:FindFirstChildOfClass("UIStroke") or Instance.new("UIStroke")
	stroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	stroke.Color = IDLE_STROKE
	stroke.Thickness = 1
	stroke.Parent = button

	local function setSelected(selected: boolean)
		stroke.Color = if selected then SELECTED_STROKE else IDLE_STROKE
		stroke.Thickness = if selected then 2 else 1
	end

	return { button = button, setSelected = setSelected }
end

return SlotStyle
```

- Border strokes follow the UICorner radius, so the rounded corners stay clean.
- If you want readable text over busy art, add a separate Contextual stroke to a TextLabel inside the slot, not to the button.
- Thickness 2 for selection reads clearly at phone sizes without shifting layout; strokes are drawn outside the box and do not change AbsoluteSize.

# Test
```lua
local button = Instance.new("TextButton")
local slot = item.style(button)
local stroke = button:FindFirstChildOfClass("UIStroke")
check("stroke draws the border, not the text", stroke ~= nil and stroke.ApplyStrokeMode == Enum.ApplyStrokeMode.Border)
check("subtle by default", stroke.Thickness == 1 and stroke.Color == Color3.fromRGB(64, 68, 78))
slot.setSelected(true)
check("selection changes stroke only", stroke.Thickness == 2 and stroke.Color == Color3.fromRGB(90, 160, 255)
	and button.BackgroundColor3 == Color3.fromRGB(32, 34, 40))
slot.setSelected(false)
check("deselect restores", stroke.Thickness == 1)
item.style(button)
local strokes = 0
for _, c in button:GetChildren() do
	if c:IsA("UIStroke") then
		strokes += 1
	end
end
check("restyling reuses the stroke", strokes == 1)
```
