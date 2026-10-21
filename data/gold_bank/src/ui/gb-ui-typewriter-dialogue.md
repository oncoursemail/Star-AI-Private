---
id: gb-ui-typewriter-dialogue
category: ui-text
topics: MaxVisibleGraphemes, typewriter effect, dialogue, skip, Heartbeat
source: original
---
# Request
For NPC dialogue I reveal text letter by letter by setting `label.Text = text:sub(1, i)` in a loop. The words jump to the next line halfway through being typed, and RichText tags show up as broken markup mid-reveal. Is there a better way? Players should also be able to skip.

# Answer
Set the full text once and reveal it with `MaxVisibleGraphemes`: the layout (line breaks, rich text) is computed for the whole string from the start, so nothing reflows. A Heartbeat connection raises the visible count by speed times time; skipping sets it to -1 (show all) and finishes.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.Typewriter
local RunService = game:GetService("RunService")

local Typewriter = {}

export type Handle = { skip: () -> (), done: () -> boolean }

function Typewriter.play(label: TextLabel, text: string, charsPerSecond: number, onDone: (() -> ())?): Handle
	label.Text = text
	label.MaxVisibleGraphemes = 0
	local total = utf8.len(text) or #text
	local shown = 0
	local finished = false
	local connection: RBXScriptConnection? = nil

	local function finish()
		if finished then
			return
		end
		finished = true
		if connection then
			connection:Disconnect()
			connection = nil
		end
		label.MaxVisibleGraphemes = -1
		if onDone then
			onDone()
		end
	end

	connection = RunService.Heartbeat:Connect(function(dt: number)
		shown += dt * charsPerSecond
		if shown >= total then
			finish()
		else
			label.MaxVisibleGraphemes = math.floor(shown)
		end
	end)

	return {
		skip = finish,
		done = function()
			return finished
		end,
	}
end

return Typewriter
```

- `-1` means "no limit", so after finishing the label behaves like any normal label even if the text changes later.
- The count is in graphemes of the displayed text, so rich text tags are never revealed half-written; `utf8.len` is a close upper bound used only to know when to stop.
- Bind skip to the same button that advances dialogue: the first press finishes the line, the second goes to the next one.

# Test
```lua
local label = Instance.new("TextLabel")
local finished = 0
local h = item.play(label, "Welcome to the village!", 20, function()
	finished += 1
end)
check("starts hidden with full text set", label.MaxVisibleGraphemes == 0 and label.Text == "Welcome to the village!")
__frames(30, 1 / 60)
check("reveals over time", label.MaxVisibleGraphemes >= 9 and label.MaxVisibleGraphemes <= 10 and not h.done())
h.skip()
check("skip shows everything", label.MaxVisibleGraphemes == -1 and h.done() and finished == 1)
__frames(120, 1 / 60)
check("finish runs once", finished == 1)
local h2 = item.play(label, "Hi", 20)
__frames(10, 1 / 60)
check("short lines finish on their own", h2.done() and label.MaxVisibleGraphemes == -1)
```
