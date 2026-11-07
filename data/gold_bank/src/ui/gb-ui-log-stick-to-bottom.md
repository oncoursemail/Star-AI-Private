---
id: gb-ui-log-stick-to-bottom
category: ui-overflow
topics: ScrollingFrame, auto scroll, CanvasPosition, AbsoluteCanvasSize, event log
source: original
---
# Request
My combat log ScrollingFrame jumps to the bottom on every new line, which is annoying when a player scrolled up to read an older message. But if they're already at the bottom it should follow new lines. How do I get that behaviour?

# Answer
Keep a `following` flag that is re-evaluated whenever the player scrolls: true while the view is at the bottom (within a small tolerance). When the canvas size changes after a new line is laid out, scroll to the new bottom only if the flag is set. The decision is a pure function of canvas position, window height and canvas height.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.StickyLog
local StickyLog = {}

local TOLERANCE = 4

function StickyLog.atBottom(scrollY: number, windowHeight: number, canvasHeight: number): boolean
	return scrollY + windowHeight >= canvasHeight - TOLERANCE
end

function StickyLog.bottomOffset(windowHeight: number, canvasHeight: number): number
	return math.max(0, canvasHeight - windowHeight)
end

export type Log = { push: (text: string) -> (), destroy: () -> () }

function StickyLog.new(scroller: ScrollingFrame, maxLines: number): Log
	local count = 0
	local lines: { TextLabel } = {}

	local function measure(): (number, number, number)
		local y: number = scroller.CanvasPosition.Y
		local window: number = scroller.AbsoluteWindowSize.Y
		local canvas: number = scroller.AbsoluteCanvasSize.Y
		return y, window, canvas
	end

	local following = StickyLog.atBottom(measure())

	local function scrollToBottom()
		local _, window, canvas = measure()
		scroller.CanvasPosition = Vector2.new(0, StickyLog.bottomOffset(window, canvas))
	end

	local connections = {
		-- Player scrolling (and our own scrollToBottom) decides whether new lines are followed.
		scroller:GetPropertyChangedSignal("CanvasPosition"):Connect(function()
			following = StickyLog.atBottom(measure())
		end),
		-- AbsoluteCanvasSize changes after the layout pass, so react to it instead of guessing when it is ready.
		scroller:GetPropertyChangedSignal("AbsoluteCanvasSize"):Connect(function()
			if following then
				scrollToBottom()
			end
		end),
	}

	local function push(text: string)
		count += 1
		local line = Instance.new("TextLabel")
		line.Name = "Line"
		line.LayoutOrder = count
		line.Size = UDim2.new(1, 0, 0, 20)
		line.BackgroundTransparency = 1
		line.TextXAlignment = Enum.TextXAlignment.Left
		line.TextSize = 15
		line.TextColor3 = Color3.fromRGB(225, 225, 230)
		line.Text = text
		line.Parent = scroller
		table.insert(lines, line)
		if #lines > maxLines then
			local oldest = lines[1]
			for i = 1, #lines do
				lines[i] = lines[i + 1]
			end
			oldest:Destroy()
		end
	end

	local function destroy()
		for _, connection in connections do
			connection:Disconnect()
		end
	end

	return { push = push, destroy = destroy }
end

return StickyLog
```

- The scroller needs a UIListLayout sorted by LayoutOrder and `AutomaticCanvasSize = Y`.
- Capping the log at `maxLines` keeps a long fight from creating thousands of labels.
- The 4 px tolerance absorbs sub-pixel scroll positions on touch devices, where "at the bottom" is rarely exact.

# Test
```lua
check("at bottom", item.atBottom(300, 200, 500))
check("within tolerance", item.atBottom(297, 200, 500))
check("scrolled up", not item.atBottom(100, 200, 500))
check("short content counts as bottom", item.atBottom(0, 200, 150))
check("bottom offset clamps", item.bottomOffset(200, 150) == 0 and item.bottomOffset(200, 500) == 300)
local scroller = Instance.new("ScrollingFrame")
scroller.CanvasPosition = Vector2.new(0, 300)
scroller.AbsoluteWindowSize = Vector2.new(300, 200)
scroller.AbsoluteCanvasSize = Vector2.new(300, 500)
local log = item.new(scroller, 3)
log.push("Hit for 12")
scroller.AbsoluteCanvasSize = Vector2.new(300, 520)
check("follows when at the bottom", scroller.CanvasPosition.Y == 320)
scroller.CanvasPosition = Vector2.new(0, 50)
log.push("Hit for 8")
scroller.AbsoluteCanvasSize = Vector2.new(300, 540)
check("stays put when scrolled up", scroller.CanvasPosition.Y == 50)
scroller.CanvasPosition = Vector2.new(0, 340)
scroller.AbsoluteCanvasSize = Vector2.new(300, 560)
check("scrolling back down resumes following", scroller.CanvasPosition.Y == 360)
log.push("c")
log.push("d")
local n = 0
for _, ch in scroller:GetChildren() do
	if ch:IsA("TextLabel") then
		n += 1
	end
end
check("old lines trimmed", n == 3)
```
