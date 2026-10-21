---
id: gb-ui-scale-vs-offset-hud
category: ui-layout
topics: UDim2, Scale, Offset, UIAspectRatioConstraint, UISizeConstraint, responsive HUD
source: original
---
# Request
My coin counter is `UDim2.new(0, 300, 0, 80)` in the top right corner. On my PC it looks fine, on my phone it covers a big part of the screen and on my 4K monitor it is tiny. How should I size it so it looks the same everywhere?

# Answer
Offset is a fixed number of pixels, and a phone in landscape has far fewer of them than a desktop. Size the panel with Scale so it follows the screen, lock its shape with a UIAspectRatioConstraint, and cap the extremes with a UISizeConstraint. Anchor it at its own top-right corner so the margin stays the same on every screen.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.CoinCounter
local CoinCounter = {}

export type Counter = {
	frame: Frame,
	setCoins: (amount: number) -> (),
}

function CoinCounter.mount(parent: Instance): Counter
	local frame = Instance.new("Frame")
	frame.Name = "CoinCounter"
	frame.AnchorPoint = Vector2.new(1, 0)
	frame.Position = UDim2.new(1, -16, 0, 16)
	frame.Size = UDim2.fromScale(0.22, 0.08)
	frame.BackgroundColor3 = Color3.fromRGB(24, 26, 31)
	frame.BackgroundTransparency = 0.15

	local aspect = Instance.new("UIAspectRatioConstraint")
	aspect.AspectRatio = 3.5
	aspect.DominantAxis = Enum.DominantAxis.Width
	aspect.Parent = frame

	local limits = Instance.new("UISizeConstraint")
	limits.MinSize = Vector2.new(140, 40)
	limits.MaxSize = Vector2.new(320, 92)
	limits.Parent = frame

	local padding = Instance.new("UIPadding")
	padding.PaddingLeft = UDim.new(0.06, 0)
	padding.PaddingRight = UDim.new(0.06, 0)
	padding.PaddingTop = UDim.new(0.15, 0)
	padding.PaddingBottom = UDim.new(0.15, 0)
	padding.Parent = frame

	local label = Instance.new("TextLabel")
	label.Name = "Amount"
	label.BackgroundTransparency = 1
	label.Size = UDim2.fromScale(1, 1)
	label.TextScaled = true
	label.TextXAlignment = Enum.TextXAlignment.Right
	label.TextColor3 = Color3.fromRGB(245, 245, 245)
	label.Text = "0"
	label.Parent = frame

	frame.Parent = parent

	local function setCoins(amount: number)
		label.Text = tostring(math.max(0, math.floor(amount)))
	end

	return { frame = frame, setCoins = setCoins }
end

return CoinCounter
```

- Scale (0.22 of the screen width) keeps the counter the same share of the screen on phone, tablet and PC; the aspect constraint then derives the height from that width.
- The 16 px margin stays Offset on purpose: margins that grow with the screen look loose on large monitors.
- The size constraint stops the panel from becoming unreadable on a small phone or oversized on an ultrawide.
- Use the Device Emulator in Studio to check a phone and a 4K preset before you ship.

# Test
```lua
local gui = Instance.new("ScreenGui")
local counter = item.mount(gui)
local frame = counter.frame
check("sized by scale, not pixels", frame.Size.X.Scale == 0.22 and frame.Size.X.Offset == 0)
check("anchored at its top-right corner", frame.AnchorPoint.X == 1 and frame.AnchorPoint.Y == 0)
check("shape and limits are constrained", frame:FindFirstChildOfClass("UIAspectRatioConstraint") ~= nil
	and frame:FindFirstChildOfClass("UISizeConstraint") ~= nil)
check("parented to the given container", frame.Parent == gui)
counter.setCoins(1250.9)
check("whole coins shown", frame.Amount.Text == "1250")
counter.setCoins(-5)
check("negative values clamp to zero", frame.Amount.Text == "0")
```
