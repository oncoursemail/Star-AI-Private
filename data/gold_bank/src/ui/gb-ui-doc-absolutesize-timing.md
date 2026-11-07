---
id: gb-ui-doc-absolutesize-timing
category: docs-question
topics: AbsoluteSize, AbsolutePosition, layout timing, GetPropertyChangedSignal, UI creation
source: original
---
# Request
I create a frame, parent it, and immediately read `frame.AbsoluteSize` to position things inside it, but it's `0, 0` (or the old size after I change Size). A `task.wait()` sometimes fixes it. When is AbsoluteSize actually correct?

# Answer
AbsoluteSize and AbsolutePosition are computed by the layout pass, which runs before the next frame renders, not at the moment you set Size or Parent. Until the object is parented under a rendered ScreenGui and a layout pass has run, the values are zero or stale. Instead of guessing with waits, react to the property: run your code now if the size is already valid, and again whenever it changes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.WhenSized
local WhenSized = {}

-- Calls `callback(size)` for the current valid size and for every later change. Returns the connection.
function WhenSized.watch(gui: GuiObject, callback: (size: Vector2) -> ()): RBXScriptConnection
	local function check()
		local size: Vector2 = gui.AbsoluteSize
		if size.X > 0 and size.Y > 0 then
			callback(size)
		end
	end
	local connection = gui:GetPropertyChangedSignal("AbsoluteSize"):Connect(check)
	check()
	return connection
end

return WhenSized
```

- Layout objects (UIListLayout, UIGridLayout) have the same timing for `AbsoluteContentSize`; watch it the same way.
- Re-running on every change also handles window resizes and phone rotation, which a one-time wait never would.
- Prefer layout objects and Scale over manual pixel math when you can; then the engine does the timing for you.

# Test
```lua
local frame = Instance.new("Frame")
frame.AbsoluteSize = Vector2.zero
local seen = {}
local conn = item.watch(frame, function(size)
	table.insert(seen, size.X)
end)
check("no callback while unsized", #seen == 0)
frame.AbsoluteSize = Vector2.new(300, 200)
check("called once the layout runs", #seen == 1 and seen[1] == 300)
frame.AbsoluteSize = Vector2.new(400, 200)
check("called again on resize", #seen == 2 and seen[2] == 400)
conn:Disconnect()
frame.AbsoluteSize = Vector2.new(500, 200)
check("disconnect stops updates", #seen == 2)
```
