---
id: gb-ui-toast-queue
category: ui-interaction
topics: toast, notification queue, task.delay, UIListLayout, dedupe
source: original
---
# Request
When a player picks up ten items at once, my notification code stacks ten labels on top of each other and they cover the screen. I want at most three toasts on screen, the rest waiting their turn, and the same message not queued twice.

# Answer
Keep two lists: the labels on screen and the texts waiting. A toast removes itself after its duration and pulls the next waiting text in. A UIListLayout anchored to the bottom stacks the visible ones, so no manual positioning is needed.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.ToastQueue
local ToastQueue = {}

export type Options = { maxVisible: number?, duration: number? }
export type Queue = {
	push: (text: string) -> (),
	visibleCount: () -> number,
	pendingCount: () -> number,
}

function ToastQueue.new(container: GuiObject, options: Options?): Queue
	local maxVisible = options and options.maxVisible or 3
	local duration = options and options.duration or 3
	local pending: { string } = {}
	local visible: { TextLabel } = {}
	local order = 0

	local layout = Instance.new("UIListLayout")
	layout.SortOrder = Enum.SortOrder.LayoutOrder
	layout.VerticalAlignment = Enum.VerticalAlignment.Bottom
	layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
	layout.Padding = UDim.new(0, 6)
	layout.Parent = container

	local showNext: () -> ()

	local function dismiss(label: TextLabel)
		local index = table.find(visible, label)
		if index then
			-- order inside `visible` does not matter (LayoutOrder sorts on screen), so swap-pop
			visible[index] = visible[#visible]
			visible[#visible] = nil
			label:Destroy()
			showNext()
		end
	end

	showNext = function()
		while #visible < maxVisible and #pending > 0 do
			local text = pending[1]
			for i = 1, #pending do
				pending[i] = pending[i + 1]
			end
			order += 1
			local label = Instance.new("TextLabel")
			label.Name = "Toast"
			label.LayoutOrder = order
			label.Size = UDim2.new(1, 0, 0, 36)
			label.BackgroundColor3 = Color3.fromRGB(30, 32, 38)
			label.BackgroundTransparency = 0.1
			label.TextColor3 = Color3.fromRGB(240, 240, 240)
			label.TextSize = 18
			label.TextTruncate = Enum.TextTruncate.AtEnd
			label.Text = text
			label.Parent = container
			table.insert(visible, label)
			task.delay(duration, dismiss, label)
		end
	end

	local function isQueuedOrShown(text: string): boolean
		if table.find(pending, text) then
			return true
		end
		for _, label in visible do
			if label.Text == text then
				return true
			end
		end
		return false
	end

	local function push(text: string)
		if text == "" or isQueuedOrShown(text) then
			return
		end
		table.insert(pending, text)
		showNext()
	end

	return {
		push = push,
		visibleCount = function()
			return #visible
		end,
		pendingCount = function()
			return #pending
		end,
	}
end

return ToastQueue
```

- New toasts get a higher LayoutOrder, so with bottom alignment the newest sits at the bottom, closest to where the eye already is.
- `TextTruncate` keeps a long item name on one line instead of pushing the stack upward.
- Dedupe by text stops "+1 Wood" spam; if you want counts, keep a number per text and show "+5 Wood" instead.

# Test
```lua
local container = Instance.new("Frame")
local q = item.new(container, { maxVisible = 2, duration = 3 })
q.push("Wood")
q.push("Stone")
q.push("Iron")
q.push("Iron")
q.push("Wood")
check("only two on screen", q.visibleCount() == 2)
check("duplicates are not queued", q.pendingCount() == 1)
__advance(3)
check("next toast moves up after the first expire", q.visibleCount() == 1 and q.pendingCount() == 0)
local remaining = container:FindFirstChildOfClass("TextLabel")
check("the waiting text is the one shown", remaining ~= nil and remaining.Text == "Iron")
__advance(3)
check("all toasts gone and destroyed", q.visibleCount() == 0 and container:FindFirstChildOfClass("TextLabel") == nil)
q.push("")
check("empty text ignored", q.visibleCount() == 0)
```
