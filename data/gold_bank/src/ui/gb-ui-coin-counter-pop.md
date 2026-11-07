---
id: gb-ui-coin-counter-pop
category: ui-style
topics: UIScale, tween pop, feedback animation, interruption, coin counter
source: original
---
# Request
I want my coin counter to do a small "pop" when coins are added: grow a little and settle back. When coins come in quickly, my version keeps growing bigger and bigger because each tween starts from the already enlarged size.

# Answer
Animate a UIScale rather than Size, and always pop from the rest scale: cancel any running tweens, snap to 1, then tween up and back. Because each pop starts from 1, rapid gains restart the pop instead of compounding it.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Pop
local TweenService = game:GetService("TweenService")

local Pop = {}

local UP = TweenInfo.new(0.08, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
local DOWN = TweenInfo.new(0.18, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

export type Popper = { pop: () -> (), scale: UIScale }

function Pop.attach(gui: GuiObject, peak: number?): Popper
	local scale = gui:FindFirstChildOfClass("UIScale") or Instance.new("UIScale")
	scale.Scale = 1
	scale.Parent = gui
	local top = peak or 1.12
	local running: { Tween } = {}

	local function cancelAll()
		for _, tween in running do
			tween:Cancel()
		end
		running = {}
	end

	local function pop()
		cancelAll()
		scale.Scale = 1
		local up = TweenService:Create(scale, UP, { Scale = top })
		local down = TweenService:Create(scale, DOWN, { Scale = 1 })
		running = { up, down }
		up.Completed:Connect(function(state: Enum.PlaybackState)
			if state == Enum.PlaybackState.Completed then
				down:Play()
			end
		end)
		up:Play()
	end

	return { pop = pop, scale = scale }
end

return Pop
```

- UIScale scales around the element's AnchorPoint, so anchor the counter at its centre for a symmetric pop.
- Tweening the UIScale leaves the label's own Size untouched, so the pop never fights the code or constraints that size the counter.
- Respect reduced motion by skipping `pop` when the player has it enabled; the number change itself is the feedback.

# Test
```lua
local label = Instance.new("TextLabel")
local p = item.attach(label, 1.12)
p.pop()
__advance(0.08)
check("grows to the peak", math.abs(p.scale.Scale - 1.12) < 1e-9)
__advance(0.2)
check("settles back to rest", p.scale.Scale == 1)
p.pop()
__advance(0.05)
p.pop()
__advance(0.05)
p.pop()
__advance(0.08)
check("rapid pops never exceed the peak", p.scale.Scale <= 1.12 + 1e-9)
__advance(0.3)
check("ends at rest after rapid pops", p.scale.Scale == 1)
local again = item.attach(label)
check("reuses the existing UIScale", again.scale == p.scale)
```
