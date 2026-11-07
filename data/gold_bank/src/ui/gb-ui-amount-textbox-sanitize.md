---
id: gb-ui-amount-textbox-sanitize
category: ui-interaction
topics: TextBox, input validation, numeric field, FocusLost, clamp
source: original
---
# Request
I have a TextBox where players type how many potions to sell. People type letters, negative numbers, "1e9" and empty strings, and my `tonumber(box.Text)` code errors or sends nonsense. How do I make a proper numeric amount field?

# Answer
Clean the text as it is typed (digits only, limited length) and settle the final value when focus is lost: parse, clamp to 1..max, and write the clamped number back so what the player sees is what will be sent. The server still validates the amount it receives.

```lua
--!strict
-- ModuleScript: ReplicatedStorage.AmountBox
local AmountBox = {}

export type Field = { value: () -> number, setMax: (max: number) -> () }

function AmountBox.digitsOnly(text: string, maxLength: number): string
	local digits = string.gsub(text, "%D", "")
	return string.sub(digits, 1, maxLength)
end

function AmountBox.settle(text: string, max: number): number
	local n = tonumber(text)
	if n == nil then
		return 1
	end
	return math.clamp(math.floor(n), 1, math.max(1, max))
end

function AmountBox.bind(box: TextBox, initialMax: number, onChanged: (amount: number) -> ()): Field
	local max = initialMax
	local amount = AmountBox.settle(box.Text, max)
	local maxLength = #tostring(max)
	box.ClearTextOnFocus = false
	box.Text = tostring(amount)

	box:GetPropertyChangedSignal("Text"):Connect(function()
		local cleaned = AmountBox.digitsOnly(box.Text, maxLength)
		if cleaned ~= box.Text then
			box.Text = cleaned
		end
	end)

	box.FocusLost:Connect(function()
		amount = AmountBox.settle(box.Text, max)
		box.Text = tostring(amount)
		onChanged(amount)
	end)

	return {
		value = function()
			return amount
		end,
		setMax = function(newMax: number)
			max = newMax
			maxLength = #tostring(newMax)
			amount = AmountBox.settle(tostring(amount), max)
			box.Text = tostring(amount)
		end,
	}
end

return AmountBox
```

- Writing the cleaned text back only when it differs avoids an endless Text-changed loop.
- Limiting length to the digits of `max` blocks pasting a 400-digit number before it is ever parsed.
- Set `max` from what the player owns; when the stack shrinks, `setMax` pulls the shown amount down with it.

# Test
```lua
check("letters and signs stripped", item.digitsOnly("-12a3.5", 6) == "1235")
check("length limited", item.digitsOnly("123456789", 3) == "123")
check("empty settles to 1", item.settle("", 50) == 1)
check("clamped to max", item.settle("999", 50) == 50)
local box = Instance.new("TextBox")
box.Text = ""
local last = nil
local field = item.bind(box, 20, function(n)
	last = n
end)
check("starts at 1", box.Text == "1" and field.value() == 1)
box.Text = "3x5"
check("typing is cleaned live", box.Text == "35")
box:ReleaseFocus(true)
check("focus lost clamps and reports", box.Text == "20" and last == 20 and field.value() == 20)
field.setMax(8)
check("shrinking max lowers the amount", field.value() == 8 and box.Text == "8")
```
