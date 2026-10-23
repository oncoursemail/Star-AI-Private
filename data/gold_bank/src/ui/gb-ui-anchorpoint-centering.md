---
id: gb-ui-anchorpoint-centering
category: ui-layout
topics: AnchorPoint, Position, centering, UDim2, layout helper
source: original
---
# Request
I want my popup in the middle of the screen, so I set the position to half the screen, but the popup ends up down and to the right of the centre. What am I doing wrong?

```lua
popup.Size = UDim2.new(0, 400, 0, 250)
popup.Position = UDim2.new(0.5, 0, 0.5, 0)
```

# Answer
Position places the frame's AnchorPoint, which defaults to its top-left corner, so your popup's corner sits at the centre. Set `AnchorPoint = Vector2.new(0.5, 0.5)` and the frame's own centre lands there. A tiny helper that always sets the two together keeps every screen edge placement consistent.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Place
local Place = {}

export type Spot = "center" | "top" | "bottom" | "left" | "right" | "topLeft" | "topRight" | "bottomLeft" | "bottomRight"

local ANCHORS: { [Spot]: Vector2 } = {
	center = Vector2.new(0.5, 0.5),
	top = Vector2.new(0.5, 0),
	bottom = Vector2.new(0.5, 1),
	left = Vector2.new(0, 0.5),
	right = Vector2.new(1, 0.5),
	topLeft = Vector2.new(0, 0),
	topRight = Vector2.new(1, 0),
	bottomLeft = Vector2.new(0, 1),
	bottomRight = Vector2.new(1, 1),
}

-- The anchor doubles as the scale position; the margin pushes inward from whichever edge the anchor touches.
function Place.at(gui: GuiObject, spot: Spot, margin: number?)
	local anchor = ANCHORS[spot]
	assert(anchor ~= nil, "unknown spot")
	local m = margin or 0
	local dx = if anchor.X == 0 then m elseif anchor.X == 1 then -m else 0
	local dy = if anchor.Y == 0 then m elseif anchor.Y == 1 then -m else 0
	gui.AnchorPoint = anchor
	gui.Position = UDim2.new(anchor.X, dx, anchor.Y, dy)
end

return Place
```

```lua
--!strict
local Place = require(game:GetService("ReplicatedStorage"):WaitForChild("Place"))

local function placePopup(popup: Frame)
	popup.Size = UDim2.fromScale(0.4, 0.35)
	Place.at(popup, "center")
end

return placePopup
```

- AnchorPoint also controls which way a frame grows when its size changes: a centred popup grows evenly in all directions.
- `bottom` with a margin is the usual spot for toasts, `topRight` for currency counters.
- The anchor works the same for Scale and Offset sizes, so the fix does not depend on how the popup is sized.

# Test
```lua
local frame = Instance.new("Frame")
item.at(frame, "center")
check("centre anchor", frame.AnchorPoint.X == 0.5 and frame.AnchorPoint.Y == 0.5)
check("centre position", frame.Position.X.Scale == 0.5 and frame.Position.Y.Scale == 0.5 and frame.Position.X.Offset == 0)
item.at(frame, "bottom", 24)
check("bottom margin pushes up", frame.Position.Y.Scale == 1 and frame.Position.Y.Offset == -24 and frame.AnchorPoint.Y == 1)
item.at(frame, "topRight", 10)
check("top-right margin pushes inward", frame.Position.X.Offset == -10 and frame.Position.Y.Offset == 10)
check("unknown spot is rejected", not pcall(item.at, frame, "middle" :: any))
```
